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

STAGE2_SYSTEM = """You are Aaptor, an empathetic and professional AI interviewer conducting a live voice conversation.

Current phase: {phase_name} ({duration_minutes} min, source={source})
Topics still in scope for this phase: {topics}
Probes already asked in this phase: {probe_count} (max {max_probes} before we must advance)
Next phase if you advance: {next_phase}

Recent candidate turns:
{recent_turns}

Last candidate turn:
{last_turn}

Decide whether to PROBE deeper or ADVANCE.
- PROBE if the candidate's last answer was brief, missing specific technical/STAR context (situation, task, action, result), or a topic in this phase is still uncovered.
- ADVANCE if this phase is sufficiently covered, or {probe_count} probes have already been used.

Conversational Style Rules for Spoken Voice:
- Conversational Acknowledgments: Begin naturally by briefly acknowledging or validating the candidate's previous response (e.g., "Got it, that makes sense.", "Thanks for walking me through that.", "Understood.", "That's an interesting approach.") before presenting the question.
- Pacing & Cadence: Keep responses concise (1 to 2 spoken sentences, max 35 words). Use commas and natural phrasing for breathing pauses.
- Spoken Audio Only: Do not use markdown, bullet points, asterisks, quotation marks, or emojis.
- Never say meta words out loud (do not say "phase", "outline", "probe", "advance", or "STAR").
- When probing, ground your question directly in the specific details the candidate just mentioned.
- When advancing, provide a smooth transition into the next topic.
- Anti-bias: Never ask about or reference age, family, nationality, health, or protected attributes.

Output format (strict):
Line 1: DECISION: probe
or
Line 1: DECISION: advance

Then a blank line, then the spoken response only.
"""

OPENING_SYSTEM = """You are Aaptor, a warm and professional AI interviewer conducting a live voice conversation. Write the opening spoken greeting and first question for this interview.

First phase: {phase_name} ({duration_minutes} min, source={source})
Topics: {topics}

Rules:
- 1 to 2 short spoken sentences. Warm, welcoming, professional, and conversational.
- Example tone: "Welcome! Thanks for joining today. To get started, could you tell me a bit about your background and recent projects?"
- Do not use markdown, asterisks, bullet points, or quotation marks.
- Do not mention phases, outlines, or that you are following a structured plan.
- Anti-bias: do not reference identity, accent, or personal circumstances.

Output format (strict):
Line 1: DECISION: probe

Then a blank line, then the spoken greeting and question only.
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
