"""Provider-neutral interview question flow."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Protocol

logger = logging.getLogger("voice-agent.aaptor")

MAX_PROBES_PER_PHASE = int(os.getenv("MAX_PROBES_PER_PHASE", "2"))
FALLBACK_OPENING = (
    "Thanks for joining. To get started, could you walk me through your "
    "background and the work that's most relevant to this role?"
)
CLOSING_MESSAGE = (
    "Thank you for your time and for sharing your experience. "
    "This concludes the interview."
)
FALLBACK_FOLLOWUP = (
    "Thank you. Could you describe the specific actions you took and the "
    "result you achieved?"
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


class LlmClient(Protocol):
    async def generate_reply(self, messages: list[dict], **kwargs) -> str: ...


def phase_topics(phase: dict) -> str:
    topics = phase.get("topics") or []
    return ", ".join(topics) if topics else "(none listed)"


def parse_stage2(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    decision = "probe"
    match = re.search(r"DECISION:\s*(probe|advance)", text, flags=re.IGNORECASE)
    if match:
        decision = match.group(1).lower()
        text = text[match.end() :].lstrip(" \t:-").lstrip("\n").strip()
    text = re.sub(
        r"^DECISION:\s*(probe|advance)\s*", "", text, flags=re.IGNORECASE
    ).strip()
    if not text:
        text = FALLBACK_OPENING
    return decision, text


class SpokenQuestionStream:
    """Strip the DECISION line from a streaming Stage-2 completion."""

    def __init__(self) -> None:
        self.buffer = ""
        self.decision: str | None = None
        self._speech_emitted = 0

    def push(self, delta: str) -> str:
        self.buffer += delta or ""
        match = re.search(r"DECISION:\s*(probe|advance)", self.buffer, flags=re.IGNORECASE)
        if not match:
            return ""
        rest = self.buffer[match.end() :]
        newline = rest.find("\n")
        if newline < 0:
            return ""
        self.decision = match.group(1).lower()
        speech = rest[newline + 1 :].lstrip()
        if len(speech) <= self._speech_emitted:
            return ""
        extra = speech[self._speech_emitted :]
        self._speech_emitted = len(speech)
        return extra

    def finish(self) -> str:
        if self._speech_emitted:
            return ""
        _, question = parse_stage2(self.buffer)
        return question


class InterviewFlow:
    """State and question generation independent of LiveKit transport."""

    def __init__(
        self,
        outline: dict,
        llm_client: LlmClient,
        *,
        max_probes_per_phase: int = MAX_PROBES_PER_PHASE,
        initial_phase_index: int = 0,
        initial_probe_count: int = 0,
        candidate_turns: list[str] | None = None,
    ) -> None:
        self.outline = outline
        self.llm_client = llm_client
        self.max_probes_per_phase = max_probes_per_phase
        self.phases: list[dict] = list(outline.get("phases") or [])
        self.phase_index = max(0, min(initial_phase_index, max(len(self.phases) - 1, 0)))
        self.probe_count = max(0, initial_probe_count)
        self.candidate_turns = list(candidate_turns or [])
        self.completed = False
        self.started_at = time.monotonic()
        self.max_duration_seconds = max(
            60,
            sum(max(int(phase.get("duration_minutes", 0)), 0) for phase in self.phases)
            * 60,
        )

    def current_phase(self) -> dict:
        if not self.phases:
            return {
                "name": "warm-up",
                "duration_minutes": 5,
                "topics": ["background"],
                "source": "generic",
            }
        return self.phases[min(self.phase_index, len(self.phases) - 1)]

    def next_phase(self) -> dict | None:
        next_index = self.phase_index + 1
        if next_index < len(self.phases):
            return self.phases[next_index]
        return None

    def apply_decision(self, decision: str) -> None:
        at_last = self.phase_index >= max(len(self.phases) - 1, 0)
        must_advance = (
            self.probe_count >= self.max_probes_per_phase
        )
        if at_last and (decision == "advance" or must_advance):
            self.completed = True
            logger.info(
                "interview_completed",
                extra={"event": "interview_completed", "phase_index": self.phase_index},
            )
            return
        if (decision == "advance" or must_advance) and not at_last:
            previous = self.current_phase().get("name")
            self.phase_index += 1
            self.probe_count = 0
            logger.info(
                "phase_advanced",
                extra={
                    "event": "phase_advanced",
                    "from_phase": previous,
                    "to_phase": self.current_phase().get("name"),
                    "forced": must_advance and decision != "advance",
                },
            )
        else:
            self.probe_count += 1

    async def generate_next_question(self, last_candidate_turn: str | None) -> str:
        if self.completed:
            return CLOSING_MESSAGE
        if time.monotonic() - self.started_at >= self.max_duration_seconds:
            if last_candidate_turn:
                self.candidate_turns.append(last_candidate_turn.strip())
            self.completed = True
            return CLOSING_MESSAGE
        if (
            last_candidate_turn
            and self.next_phase() is None
            and self.probe_count >= self.max_probes_per_phase
        ):
            self.candidate_turns.append(last_candidate_turn.strip())
            self.completed = True
            return CLOSING_MESSAGE
        phase = self.current_phase()
        next_phase = self.next_phase()
        next_phase_label = (
            f"{next_phase.get('name')} — topics: {phase_topics(next_phase)}"
            if next_phase
            else "none (closing)"
        )
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        recent = self.candidate_turns[-2:]

        if last_candidate_turn:
            prompt = STAGE2_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=phase_topics(phase),
                probe_count=self.probe_count,
                max_probes=self.max_probes_per_phase,
                next_phase=next_phase_label,
                recent_turns="\n".join(f"- {turn}" for turn in recent)
                or "(none yet)",
                last_turn=last_candidate_turn,
            )
            user_content = last_candidate_turn
        else:
            prompt = OPENING_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=phase_topics(phase),
            )
            user_content = "Generate the opening question now."

        started = time.perf_counter()
        try:
            raw = await self.llm_client.generate_reply(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ]
            )
        except Exception:
            logger.exception(
                "stage2_question_failed",
                extra={"event": "stage2_question_failed"},
            )
            if last_candidate_turn:
                self.candidate_turns.append(last_candidate_turn)
                self.apply_decision("probe")
            return FALLBACK_FOLLOWUP if not self.completed else CLOSING_MESSAGE
        decision, question = parse_stage2(raw)
        if last_candidate_turn:
            self.candidate_turns.append(last_candidate_turn)
            self.apply_decision(decision)
            if self.completed:
                question = CLOSING_MESSAGE
        logger.info(
            "stage2_question",
            extra={
                "event": "stage2_question",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "decision": decision,
                "phase": self.current_phase().get("name"),
                "phase_index": self.phase_index,
                "probe_count": self.probe_count,
                "is_opening": last_candidate_turn is None,
            },
        )
        return question

    def _commit_turn(
        self,
        last_candidate_turn: str | None,
        decision: str,
        *,
        started: float,
        is_opening: bool,
    ) -> None:
        if last_candidate_turn:
            self.candidate_turns.append(last_candidate_turn)
            self.apply_decision(decision)
        logger.info(
            "stage2_question",
            extra={
                "event": "stage2_question",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "decision": decision,
                "phase": self.current_phase().get("name"),
                "phase_index": self.phase_index,
                "probe_count": self.probe_count,
                "is_opening": is_opening,
            },
        )

    async def generate_next_question_stream(self, last_candidate_turn: str | None):
        stream = getattr(self.llm_client, "generate_reply_stream", None) or getattr(
            self.llm_client, "stream_reply", None
        )
        if stream is None:
            yield await self.generate_next_question(last_candidate_turn)
            return

        phase = self.current_phase()
        next_phase = self.next_phase()
        next_phase_label = (
            f"{next_phase.get('name')} — topics: {phase_topics(next_phase)}"
            if next_phase
            else "none (closing)"
        )
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        recent = self.candidate_turns[-2:]

        if last_candidate_turn:
            prompt = STAGE2_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=phase_topics(phase),
                probe_count=self.probe_count,
                max_probes=self.max_probes_per_phase,
                next_phase=next_phase_label,
                recent_turns="\n".join(f"- {turn}" for turn in recent)
                or "(none yet)",
                last_turn=last_candidate_turn,
            )
            user_content = last_candidate_turn
        else:
            prompt = OPENING_SYSTEM.format(
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                source=phase.get("source", "generic"),
                topics=phase_topics(phase),
            )
            user_content = "Generate the opening question now."

        started = time.perf_counter()
        parser = SpokenQuestionStream()
        async for delta in stream(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ]
        ):
            spoken = parser.push(delta)
            if spoken:
                yield spoken
        leftover = parser.finish()
        if leftover:
            yield leftover
        self._commit_turn(
            last_candidate_turn,
            parser.decision or "probe",
            started=started,
            is_opening=last_candidate_turn is None,
        )
