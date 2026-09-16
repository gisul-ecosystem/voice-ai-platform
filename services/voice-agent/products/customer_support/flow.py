"""Provider-neutral customer-support conversation flow."""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from clients.errors import ServiceUnavailableError

logger = logging.getLogger("voice-agent.racko")

MAX_UNRESOLVED_ATTEMPTS = 2

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


class LlmClient(Protocol):
    async def generate_reply(self, messages: list[dict], **kwargs) -> str: ...


DataLookup = Callable[[str], Awaitable[dict]]
ContextLookup = Callable[[str], Awaitable[list[str]]]


def parse_intent(raw: str) -> str:
    match = re.search(
        r"INTENT:\s*(billing|order|general|escalation)", raw or "", re.I
    )
    if match:
        return match.group(1).lower()
    lowered = (raw or "").lower()
    if any(
        word in lowered
        for word in ("human", "supervisor", "representative", "real person")
    ):
        return "escalation"
    return "general"


def parse_resolved(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    resolved = True
    match = re.search(r"RESOLVED:\s*(yes|no)", text, flags=re.IGNORECASE)
    if match:
        resolved = match.group(1).lower() == "yes"
        text = text[match.end() :].lstrip(" \t:-").lstrip("\n").strip()
    text = re.sub(
        r"^RESOLVED:\s*(yes|no)\s*", "", text, flags=re.IGNORECASE
    ).strip()
    if not text:
        text = "I want to make sure I have this right. Could you share a bit more detail?"
        resolved = False
    return resolved, text


def looks_like_id(token: str) -> bool:
    value = (token or "").strip("-#")
    return bool(
        re.fullmatch(r"\d{3,12}", value)
        or re.fullmatch(r"[A-Za-z]{1,4}-\d{3,8}", value)
        or re.fullmatch(r"[A-Za-z]{2,4}\d{3,8}", value)
    )


def extract_id(user_text: str, intent: str) -> str | None:
    for match in _ID_RE.finditer(user_text or ""):
        prefix = match.group(0).lower()
        token = match.group(1).strip("-#")
        if not looks_like_id(token):
            continue
        if intent == "order" and "acc" in prefix:
            continue
        if intent == "billing" and "ord" in prefix:
            continue
        return token
    bare = _BARE_ID_RE.search(user_text or "")
    if bare and looks_like_id(bare.group(1)):
        return bare.group(1)
    return None


def wants_human(user_text: str) -> bool:
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
    return any(phrase in lowered for phrase in phrases)


class SupportFlow:
    """Intent → tools/context → response state independent of LiveKit."""

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        fetch_account: DataLookup,
        fetch_invoice: DataLookup,
        fetch_order: DataLookup,
        retrieve: ContextLookup,
        session_id: str = "",
        max_unresolved_attempts: int = MAX_UNRESOLVED_ATTEMPTS,
    ) -> None:
        self.llm_client = llm_client
        self.fetch_account = fetch_account
        self.fetch_invoice = fetch_invoice
        self.fetch_order = fetch_order
        self.retrieve = retrieve
        self.session_id = session_id
        self.max_unresolved_attempts = max_unresolved_attempts
        self.unresolved_attempts = 0
        self.escalated = False
        self.last_account_id: str | None = None
        self.last_order_id: str | None = None

    async def classify(self, user_text: str) -> str:
        if wants_human(user_text):
            return "escalation"
        raw = await self.llm_client.generate_reply(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": user_text},
            ]
        )
        intent = parse_intent(raw)
        logger.info(
            "intent_classified",
            extra={"event": "intent_classified", "intent": intent},
        )
        return intent

    def entity_id_for_intent(self, intent: str, user_text: str) -> str | None:
        extracted = extract_id(user_text, intent)
        if intent == "billing":
            return extracted or self.last_account_id
        if intent == "order":
            return extracted or self.last_order_id
        return extracted

    async def tool_payload(
        self, intent: str, user_text: str, entity_id: str
    ) -> dict | None:
        if intent == "billing":
            self.last_account_id = entity_id
            if "invoice" in user_text.lower():
                return await self.fetch_invoice(entity_id)
            return await self.fetch_account(entity_id)
        if intent == "order":
            self.last_order_id = entity_id
            return await self.fetch_order(entity_id)
        return None

    async def kb_snippets(self, user_text: str) -> list[str]:
        try:
            return await self.retrieve(user_text)
        except ServiceUnavailableError:
            logger.exception("retrieve_failed", extra={"event": "retrieve_failed"})
            return []

    def trigger_escalation(self, reason: str, user_text: str) -> str:
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
        intent = await self.classify(user_text)
        if intent == "escalation":
            return self.trigger_escalation("customer_requested_human", user_text)

        tool_result: dict[str, Any] | None = None
        if intent in ("billing", "order"):
            entity_id = self.entity_id_for_intent(intent, user_text)
            if not entity_id:
                logger.info(
                    "cs_turn",
                    extra={
                        "event": "cs_turn",
                        "stage": "llm",
                        "latency_ms": round(
                            (time.perf_counter() - started) * 1000, 1
                        ),
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
                tool_result = await self.tool_payload(intent, user_text, entity_id)
            except ServiceUnavailableError:
                logger.exception(
                    "tool_failed", extra={"event": "tool_failed", "intent": intent}
                )

        kb: list[str] = []
        if intent in ("general", "billing", "order"):
            kb = await self.kb_snippets(user_text)

        raw = await self.llm_client.generate_reply(
            [
                {
                    "role": "system",
                    "content": REPLY_SYSTEM.format(
                        intent=intent,
                        tool_result=json.dumps(tool_result)
                        if tool_result
                        else "(none)",
                        kb_snippets="\n".join(kb) if kb else "(none)",
                        user_text=user_text,
                    ),
                },
                {"role": "user", "content": user_text},
            ]
        )
        resolved, spoken = parse_resolved(raw)
        if resolved:
            self.unresolved_attempts = 0
        else:
            self.unresolved_attempts += 1
            if self.unresolved_attempts >= self.max_unresolved_attempts:
                spoken = self.trigger_escalation("unresolved_after_retries", user_text)

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
