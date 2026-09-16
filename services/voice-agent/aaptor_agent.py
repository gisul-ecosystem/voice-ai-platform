"""
Aaptor interview orchestrator (Stage 1 + Stage 2).

livekit-agents 1.x renamed VoicePipelineAgent to AgentSession; this file
wires the same STT → LLM → TTS pipeline using the laptop HTTP clients as
the STT/LLM/TTS backends.

Stage 1 (once per session): POST backend-api /interviews/plan → outline.
Stage 2 (every turn): current outline phase + last candidate turn → next
question, deciding probe-deeper vs advance-to-next-phase.
See docs/implementation_plan.md section 1.
"""
from __future__ import annotations

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

from clients.backend_client import fetch_interview_plan  # noqa: E402
from clients.errors import ProviderConfigError, ServiceUnavailableError  # noqa: E402
from clients.inference import (  # noqa: E402
    clients_from_overrides,
    inference_overrides_from_metadata,
    parse_room_metadata,
)
from livekit_adapters import LaptopLLM, LaptopSTT, LaptopTTS  # noqa: E402

logger = logging.getLogger("voice-agent.aaptor")

MAX_PROBES_PER_PHASE = int(os.getenv("MAX_PROBES_PER_PHASE", "2"))
FALLBACK_OPENING = (
    "Thanks for joining. To get started, could you walk me through your "
    "background and the work that's most relevant to this role?"
)

STAGE2_SYSTEM = """You are Aaptor, a live AI interviewer speaking with a candidate over voice.

Current phase: {phase_name} ({duration_minutes} min, source={source})
Topics still in scope for this phase: {topics}
Probes already asked in this phase: {probe_count} (max {max_probes} before we must advance)
Next phase if you advance: {next_phase}

Recent candidate turns:
{recent_turns}

Last candidate turn:
{last_turn}

Decide whether to PROBE deeper or ADVANCE.
- PROBE if the last answer was vague, missing STAR specifics (situation, task, action, result), or a topic in this phase is still uncovered.
- ADVANCE if this phase is sufficiently covered, or {probe_count} probes have already been used.

Rules:
- Ask exactly one question as spoken English, 1-3 sentences.
- No markdown, lists, or quotation marks wrapping the question.
- Do not say the words phase, outline, probe, or advance out loud.
- When probing, ground the question in what the candidate just said.
- When advancing, ask a natural first question for the next phase's topics.
- Stay sector-agnostic. Prefer STAR behavioral framing for experience claims.
- Anti-bias: do not ask about age, family, nationality, health, or other protected attributes; do not assume identity from name or accent.

Output format (strict):
Line 1: DECISION: probe
or
Line 1: DECISION: advance
Then a blank line, then the spoken question only.
"""

OPENING_SYSTEM = """You are Aaptor, a live AI interviewer. Write the opening spoken question for this interview.

First phase: {phase_name} ({duration_minutes} min, source={source})
Topics: {topics}

Rules:
- One short spoken question (1-2 sentences). Warm, professional, no markdown.
- Do not mention phases or that you are following a plan.
- Anti-bias: do not reference identity, accent, or personal circumstances.

Output format (strict):
Line 1: DECISION: probe
Then a blank line, then the spoken question only.
"""


def _phase_topics(phase: dict) -> str:
    topics = phase.get("topics") or []
    return ", ".join(topics) if topics else "(none listed)"


def _parse_stage2(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    decision = "probe"
    match = re.search(r"DECISION:\s*(probe|advance)", text, flags=re.IGNORECASE)
    if match:
        decision = match.group(1).lower()
        text = text[match.end() :].lstrip(" \t:-").lstrip("\n").strip()
    text = re.sub(r"^DECISION:\s*(probe|advance)\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        text = FALLBACK_OPENING
    return decision, text


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


def _plan_inputs_from_job(ctx: JobContext) -> tuple[str, str]:
    meta = parse_room_metadata(getattr(ctx.room, "metadata", None) or "")
    jd = (meta.get("job_description") or os.getenv("JOB_DESCRIPTION") or "").strip()
    resume = (meta.get("resume_text") or os.getenv("RESUME_TEXT") or "").strip()
    return jd, resume


class AaptorAgent(Agent):
    """Interview flow: Stage 1 outline at session start, Stage 2 question each turn."""

    def __init__(self, outline: dict, llm_client) -> None:
        super().__init__(
            instructions=(
                "You are Aaptor, an AI interviewer. Ask one concise spoken question "
                "at a time. Do not use markdown."
            )
        )
        self.outline = outline
        self.llm_client = llm_client
        self.phases: list[dict] = list(outline.get("phases") or [])
        self.phase_index = 0
        self.probe_count = 0
        self.candidate_turns: list[str] = []

    def _current_phase(self) -> dict:
        if not self.phases:
            return {
                "name": "warm-up",
                "duration_minutes": 5,
                "topics": ["background"],
                "source": "generic",
            }
        return self.phases[min(self.phase_index, len(self.phases) - 1)]

    def _next_phase(self) -> dict | None:
        nxt = self.phase_index + 1
        if nxt < len(self.phases):
            return self.phases[nxt]
        return None

    def _apply_decision(self, decision: str) -> None:
        at_last = self.phase_index >= max(len(self.phases) - 1, 0)
        must_advance = self.probe_count >= MAX_PROBES_PER_PHASE and not at_last
        if (decision == "advance" or must_advance) and not at_last:
            prev = self._current_phase().get("name")
            self.phase_index += 1
            self.probe_count = 0
            logger.info(
                "phase_advanced",
                extra={
                    "event": "phase_advanced",
                    "from_phase": prev,
                    "to_phase": self._current_phase().get("name"),
                    "forced": must_advance and decision != "advance",
                },
            )
        else:
            self.probe_count += 1

    async def generate_next_question(self, last_candidate_turn: str | None) -> str:
        phase = self._current_phase()
        nxt = self._next_phase()
        next_phase_label = (
            f"{nxt.get('name')} — topics: {_phase_topics(nxt)}" if nxt else "none (closing)"
        )
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        recent = self.candidate_turns[-2:]

        if last_candidate_turn:
            prompt = STAGE2_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=_phase_topics(phase),
                probe_count=self.probe_count,
                max_probes=MAX_PROBES_PER_PHASE,
                next_phase=next_phase_label,
                recent_turns="\n".join(f"- {t}" for t in recent) or "(none yet)",
                last_turn=last_candidate_turn,
            )
            user_content = last_candidate_turn
        else:
            prompt = OPENING_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=_phase_topics(phase),
            )
            user_content = "Generate the opening question now."

        started = time.perf_counter()
        raw = await self.llm_client.generate_reply(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ]
        )
        decision, question = _parse_stage2(raw)
        if last_candidate_turn:
            self.candidate_turns.append(last_candidate_turn)
            self._apply_decision(decision)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "stage2_question",
            extra={
                "event": "stage2_question",
                "stage": "llm",
                "latency_ms": latency_ms,
                "decision": decision,
                "phase": self._current_phase().get("name"),
                "phase_index": self.phase_index,
                "probe_count": self.probe_count,
                "is_opening": last_candidate_turn is None,
            },
        )
        return question

    async def on_enter(self) -> None:
        question = await self.generate_next_question(last_candidate_turn=None)
        await self.session.say(question)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        last_turn = _last_user_text(chat_ctx)
        question = await self.generate_next_question(last_candidate_turn=last_turn or None)
        yield question


GENERIC_OUTLINE = {
    "phases": [
        {
            "name": "warm-up",
            "duration_minutes": 5,
            "topics": ["background", "motivation"],
            "source": "generic",
        },
        {
            "name": "core skills",
            "duration_minutes": 10,
            "topics": ["recent work", "problem solving"],
            "source": "generic",
        },
    ]
}


async def _build_outline(ctx: JobContext) -> dict:
    jd, resume = _plan_inputs_from_job(ctx)
    if not jd or not resume:
        logger.warning(
            "plan_inputs_missing",
            extra={"event": "plan_inputs_missing", "has_jd": bool(jd), "has_resume": bool(resume)},
        )
        return GENERIC_OUTLINE
    try:
        return await fetch_interview_plan(jd, resume)
    except ServiceUnavailableError:
        logger.exception(
            "stage1_plan_failed",
            extra={"event": "stage1_plan_failed"},
        )
        return GENERIC_OUTLINE


# AgentSession is the livekit-agents 1.x successor to VoicePipelineAgent.
VoicePipelineAgent = AgentSession


async def entrypoint(ctx: JobContext) -> None:
    if hasattr(ctx, "log_context_fields"):
        ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("session_start", extra={"event": "session_start", "room": ctx.room.name})
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

    outline = await _build_outline(ctx)
    logger.info(
        "stage1_outline",
        extra={
            "event": "stage1_outline",
            "phase_count": len(outline.get("phases") or []),
            "phases": [p.get("name") for p in (outline.get("phases") or [])],
        },
    )

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

    await session.start(agent=AaptorAgent(outline, llm_client), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Named agent so LiveKit Cloud explicit dispatch (roomConfig.agents) can find us.
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "aaptor"),
        )
    )
