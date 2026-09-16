"""
Racko voice CS orchestrator.

livekit-agents 1.x AgentSession with the same LaptopSTT / LaptopLLM / LaptopTTS
adapters as Aaptor. Each turn: classify intent → optional mock tool and/or
context-engine retrieve → spoken reply. Escalation is logged only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

from logging_config import configure_logging

load_dotenv()
configure_logging()

from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    JobContext,
    ModelSettings,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import silero  # noqa: E402

from clients.backend_client import (  # noqa: E402
    fetch_account_status,
    fetch_invoice_status,
    fetch_order_status,
)
from clients.context_client import retrieve_context  # noqa: E402
from clients.errors import ProviderConfigError, ServiceUnavailableError  # noqa: E402
from clients.inference import (  # noqa: E402
    clients_from_overrides,
    inference_overrides_from_metadata,
    parse_room_metadata,
)
from livekit_adapters import LaptopLLM, LaptopSTT, LaptopTTS  # noqa: E402

logger = logging.getLogger("voice-agent.racko")

MAX_UNRESOLVED_ATTEMPTS = 2

VoicePipelineAgent = AgentSession

GREETING = (
    "Hi, this is Racko support. I can help with billing, orders, or account "
    "questions. How can I help today?"
)

ESCALATION_SPOKEN = (
    "I'll pass this to a human specialist. They will follow up on this "
    "conversation. Is there anything else I should note before we hand off?"
)

ASK_ACCOUNT_ID = (
    "I can check that on your account. What's the account or invoice number?"
)
ASK_ORDER_ID = "I can check that. What's the order number?"

CLASSIFY_SYSTEM = """You classify a customer-support utterance.
Return exactly one line:
INTENT: billing
or INTENT: order
or INTENT: general
or INTENT: escalation

billing = charges, refunds, invoices, plan, account balance, card, subscription
order = shipping, delivery, tracking, package, damaged item, missing item
general = policy, FAQ, how-to, password, login, hours
escalation = customer asks for a human, agent, supervisor, or representative
If unsure, use general.
"""

REPLY_SYSTEM = """You are Racko, a voice customer-support agent. Speak one short reply.

Intent: {intent}
Tool result (may be empty): {tool_result}
Policy snippets (may be empty): {kb_snippets}

Customer said:
{user_text}

Rules:
- Spoken English, 1-4 sentences. No markdown or lists.
- Ground the answer in the tool result and snippets when they are present.
- If those are empty and you cannot help, say so plainly and ask one clarifying question.
- Do not invent order or account facts that are not in the tool result.
- Do not claim a human is on the line unless this is an escalation turn.

Output format (strict):
Line 1: RESOLVED: yes
or
Line 1: RESOLVED: no
Then a blank line, then the spoken reply only.
"""

_ID_RE = re.compile(
    r"\b(?:account|acct|acc|order|ord|invoice|inv)[\s#-]*([A-Za-z0-9-]{2,24})\b",
    flags=re.IGNORECASE,
)
_BARE_ID_RE = re.compile(r"\b([A-Z]{1,4}-\d{3,8}|\d{5,12})\b")


def _last_user_text(chat_ctx: llm.ChatContext) -> str:
    for item in reversed(list(chat_ctx.items)):
        if getattr(item, "role", None) != "user":
            continue
        text = getattr(item, "text_content", None)
        if not text:
            content = getattr(item, "content", None)
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(part for part in content if isinstance(part, str))
        if text:
            return text
    return ""


def _parse_intent(raw: str) -> str:
    match = re.search(r"INTENT:\s*(billing|order|general|escalation)", raw or "", re.I)
    if match:
        return match.group(1).lower()
    lowered = (raw or "").lower()
    if any(w in lowered for w in ("human", "supervisor", "representative", "real person")):
        return "escalation"
    return "general"


def _parse_resolved(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    resolved = True
    match = re.search(r"RESOLVED:\s*(yes|no)", text, flags=re.IGNORECASE)
    if match:
        resolved = match.group(1).lower() == "yes"
        text = text[match.end() :].lstrip(" \t:-").lstrip("\n").strip()
    text = re.sub(r"^RESOLVED:\s*(yes|no)\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        text = "I want to make sure I have this right. Could you share a bit more detail?"
        resolved = False
    return resolved, text


def _looks_like_id(token: str) -> bool:
    value = (token or "").strip("-#")
    if re.fullmatch(r"\d{3,12}", value):
        return True
    if re.fullmatch(r"[A-Za-z]{1,4}-\d{3,8}", value):
        return True
    if re.fullmatch(r"[A-Za-z]{2,4}\d{3,8}", value):
        return True
    return False


def _extract_id(user_text: str, intent: str) -> str | None:
    for match in _ID_RE.finditer(user_text or ""):
        prefix = match.group(0).lower()
        token = match.group(1).strip("-#")
        if not _looks_like_id(token):
            continue
        if intent == "order" and "acc" in prefix:
            continue
        if intent == "billing" and "ord" in prefix:
            continue
        return token
    bare = _BARE_ID_RE.search(user_text or "")
    if bare and _looks_like_id(bare.group(1)):
        return bare.group(1)
    return None


def _wants_human(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    phrases = (
        "speak to a human",
        "talk to a human",
        "real person",
        "real agent",
        "representative",
        "supervisor",
        "customer service agent",
    )
    return any(p in lowered for p in phrases)


class RackoAgent(Agent):
    """CS turn loop: intent → tools/KB → spoken reply; log-only escalation."""

    def __init__(self, llm_client, *, session_id: str = "") -> None:
        super().__init__(
            instructions=(
                "You are Racko, a voice customer-support agent. One concise spoken "
                "reply at a time. Do not use markdown."
            )
        )
        self.llm_client = llm_client
        self.session_id = session_id
        self.unresolved_attempts = 0
        self.escalated = False
        self.last_account_id: str | None = None
        self.last_order_id: str | None = None

    async def _classify(self, user_text: str) -> str:
        if _wants_human(user_text):
            return "escalation"
        raw = await self.llm_client.generate_reply(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": user_text},
            ]
        )
        intent = _parse_intent(raw)
        logger.info(
            "intent_classified",
            extra={"event": "intent_classified", "intent": intent},
        )
        return intent

    def _entity_id_for_intent(self, intent: str, user_text: str) -> str | None:
        extracted = _extract_id(user_text, intent)
        if intent == "billing":
            return extracted or self.last_account_id
        if intent == "order":
            return extracted or self.last_order_id
        return extracted

    async def _tool_payload(self, intent: str, user_text: str, entity_id: str) -> dict | None:
        if intent == "billing":
            self.last_account_id = entity_id
            if "invoice" in user_text.lower():
                return await fetch_invoice_status(entity_id)
            return await fetch_account_status(entity_id)
        if intent == "order":
            self.last_order_id = entity_id
            return await fetch_order_status(entity_id)
        return None

    async def _kb_snippets(self, user_text: str) -> list[str]:
        try:
            return await retrieve_context(user_text)
        except ServiceUnavailableError:
            logger.exception(
                "retrieve_failed",
                extra={"event": "retrieve_failed"},
            )
            return []

    def _trigger_escalation(self, reason: str, user_text: str) -> str:
        self.escalated = True
        logger.info(
            "escalation_triggered",
            extra={
                "event": "escalation_triggered",
                "session_id": self.session_id,
                "reason": reason,
                "unresolved_attempts": self.unresolved_attempts,
                "user_chars": len(user_text or ""),
            },
        )
        return ESCALATION_SPOKEN

    async def generate_reply_text(self, user_text: str | None) -> str:
        if not (user_text or "").strip():
            return GREETING
        user_text = user_text.strip()

        if self.escalated:
            return (
                "A specialist already has this thread. I'll stay on the line if you "
                "have one more detail to add."
            )

        started = time.perf_counter()
        intent = await self._classify(user_text)
        if intent == "escalation":
            return self._trigger_escalation("customer_requested_human", user_text)

        tool_result: dict | None = None
        if intent in ("billing", "order"):
            entity_id = self._entity_id_for_intent(intent, user_text)
            if not entity_id:
                logger.info(
                    "cs_turn",
                    extra={
                        "event": "cs_turn",
                        "stage": "llm",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "intent": intent,
                        "resolved": False,
                        "used_tool": False,
                        "kb_hits": 0,
                        "unresolved_attempts": self.unresolved_attempts,
                        "missing_id": True,
                    },
                )
                return ASK_ACCOUNT_ID if intent == "billing" else ASK_ORDER_ID
            try:
                tool_result = await self._tool_payload(intent, user_text, entity_id)
            except ServiceUnavailableError:
                logger.exception(
                    "tool_failed", extra={"event": "tool_failed", "intent": intent}
                )

        kb: list[str] = []
        if intent in ("general", "billing", "order"):
            kb = await self._kb_snippets(user_text)

        raw = await self.llm_client.generate_reply(
            [
                {
                    "role": "system",
                    "content": REPLY_SYSTEM.format(
                        intent=intent,
                        tool_result=json.dumps(tool_result) if tool_result else "(none)",
                        kb_snippets="\n".join(kb) if kb else "(none)",
                        user_text=user_text,
                    ),
                },
                {"role": "user", "content": user_text},
            ]
        )
        resolved, spoken = _parse_resolved(raw)
        if resolved:
            self.unresolved_attempts = 0
        else:
            self.unresolved_attempts += 1
            if self.unresolved_attempts >= MAX_UNRESOLVED_ATTEMPTS:
                spoken = self._trigger_escalation("unresolved_after_retries", user_text)

        logger.info(
            "cs_turn",
            extra={
                "event": "cs_turn",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "intent": intent,
                "resolved": resolved,
                "used_tool": tool_result is not None,
                "kb_hits": len(kb),
                "unresolved_attempts": self.unresolved_attempts,
            },
        )
        return spoken

    async def on_enter(self) -> None:
        await self.session.say(GREETING)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        last_turn = _last_user_text(chat_ctx)
        yield await self.generate_reply_text(last_turn or None)


async def entrypoint(ctx: JobContext) -> None:
    if hasattr(ctx, "log_context_fields"):
        ctx.log_context_fields = {"room": ctx.room.name}
    logger.info(
        "session_start",
        extra={"event": "session_start", "session_id": ctx.room.name, "room": ctx.room.name},
    )
    await ctx.connect()

    overrides = inference_overrides_from_metadata(
        parse_room_metadata(getattr(ctx.room, "metadata", None) or "")
    )
    try:
        llm_client, stt_client, tts_client = clients_from_overrides(overrides)
    except ProviderConfigError:
        logger.exception(
            "inference_config_invalid",
            extra={"event": "inference_config_invalid", **overrides.log_safe()},
        )
        raise

    session = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=LaptopSTT(client=stt_client),
        llm=LaptopLLM(client=llm_client),
        tts=LaptopTTS(client=tts_client),
    )

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        metrics = getattr(ev, "metrics", ev)
        kind = getattr(metrics, "type", type(metrics).__name__)
        duration_ms = None
        if hasattr(metrics, "duration"):
            duration_ms = round(float(metrics.duration) * 1000, 1)
        logger.info(
            "turn_stage_metrics",
            extra={
                "event": "turn_stage_metrics",
                "stage": kind,
                "latency_ms": duration_ms,
            },
        )

    await session.start(
        agent=RackoAgent(llm_client, session_id=ctx.room.name),
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("RACKO_AGENT_NAME", "racko"),
        )
    )
