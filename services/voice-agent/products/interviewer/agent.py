"""LiveKit adapter for the provider-neutral interview flow."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from livekit.agents import Agent, ModelSettings, llm

from products.interviewer.flow import FALLBACK_FOLLOWUP, FALLBACK_OPENING, InterviewFlow
from voice_platform.chat import is_usable_candidate_turn, last_text

CLARIFY_TURN = (
    "Sorry, I did not catch that. Please say a bit more, in a full sentence."
)


class AaptorAgent(Agent):
    """Aaptor's LiveKit surface; interview state lives in InterviewFlow."""

    def __init__(
        self,
        outline: dict,
        llm_client,
        *,
        max_probes_per_phase: int | None = None,
        job_description: str = "",
        resume_text: str = "",
        competencies: list[str] | None = None,
        min_turns_before_close: int | None = None,
        target_duration_minutes: int | None = None,
        initial_state: dict | None = None,
        turn_sink: Callable[..., Awaitable[None]] | None = None,
        status_sink: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are Aaptor, a live technical interviewer. Invent each "
                "spoken question from the resume, job, and the candidate's last "
                "answer. Sound like a person in the room."
            )
        )
        flow_kwargs: dict = {}
        if max_probes_per_phase is not None:
            flow_kwargs["max_probes_per_phase"] = max_probes_per_phase
        if job_description:
            flow_kwargs["job_description"] = job_description
        if resume_text:
            flow_kwargs["resume_text"] = resume_text
        if competencies:
            flow_kwargs["competencies"] = competencies
        if min_turns_before_close is not None:
            flow_kwargs["min_turns_before_close"] = min_turns_before_close
        if target_duration_minutes is not None:
            flow_kwargs["target_duration_minutes"] = target_duration_minutes
        restored_state = dict(initial_state or {})
        self._sequence_number = int(restored_state.pop("initial_sequence_number", 0))
        flow_kwargs.update(restored_state)
        self.flow = InterviewFlow(outline, llm_client, **flow_kwargs)
        self._turn_sink = turn_sink
        self._status_sink = status_sink
        self._completion_reported = False
        self._opened = bool(self.flow.candidate_turns)
        self._last_agent_text = ""

    async def _record(self, speaker: str, text: str) -> None:
        if self._turn_sink and text.strip():
            self._sequence_number += 1
            await self._turn_sink(
                turn_id=f"turn_{uuid.uuid4().hex}",
                speaker=speaker,
                text=text.strip(),
                phase_index=self.phase_index,
                sequence_number=self._sequence_number,
            )

    @property
    def outline(self) -> dict:
        return self.flow.outline

    @property
    def llm_client(self):
        return self.flow.llm_client

    @property
    def phases(self) -> list[dict]:
        return self.flow.phases

    @property
    def phase_index(self) -> int:
        return self.flow.phase_index

    @property
    def probe_count(self) -> int:
        return self.flow.probe_count

    @property
    def candidate_turns(self) -> list[str]:
        return self.flow.candidate_turns

    def _current_phase(self) -> dict:
        return self.flow.current_phase()

    def _next_phase(self) -> dict | None:
        return self.flow.next_phase()

    def _apply_decision(self, decision: str) -> None:
        self.flow.apply_decision(decision)

    async def generate_next_question(self, last_candidate_turn: str | None) -> str:
        return await self.flow.generate_next_question(last_candidate_turn)

    async def on_enter(self) -> None:
        parts: list[str] = []
        async for chunk in self.flow.generate_next_question_stream(None):
            parts.append(chunk)
        opening = "".join(parts).strip() or FALLBACK_OPENING
        await self.session.say(opening, allow_interruptions=False)
        self._opened = True
        self._last_agent_text = opening
        await self._record("agent", opening)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        candidate_turn = last_text(chat_ctx)
        opening = not self._opened
        if opening:
            self._opened = True
            candidate_turn = None
        elif not is_usable_candidate_turn(
            candidate_turn,
            self._last_agent_text,
            min_words=1 if not self.flow.candidate_turns else 3,
        ):
            yield CLARIFY_TURN
            self._last_agent_text = CLARIFY_TURN
            return
        elif candidate_turn:
            await self._record("candidate", candidate_turn)
        parts: list[str] = []
        async for chunk in self.flow.generate_next_question_stream(candidate_turn):
            parts.append(chunk)
            yield chunk
        question = "".join(parts).strip()
        if not question:
            question = FALLBACK_FOLLOWUP
            yield question
        if question:
            self._last_agent_text = question
            await self._record("agent", question)
        if (
            self.flow.completed
            and self._status_sink
            and not self._completion_reported
        ):
            self._completion_reported = True
            await self._status_sink("completing", reason="interview_flow_complete")
            await self._status_sink("completed", reason="closing_delivered")
