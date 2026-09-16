"""LiveKit adapter for the provider-neutral interview flow."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from livekit.agents import Agent, ModelSettings, llm

from products.interviewer.flow import InterviewFlow
from voice_platform.chat import last_text


class AaptorAgent(Agent):
    """Aaptor's LiveKit surface; interview state lives in InterviewFlow."""

    def __init__(
        self,
        outline: dict,
        llm_client,
        *,
        max_probes_per_phase: int | None = None,
        initial_state: dict | None = None,
        turn_sink: Callable[..., Awaitable[None]] | None = None,
        status_sink: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are Aaptor, an AI interviewer. Ask one concise spoken question "
                "at a time. Do not use markdown."
            )
        )
        flow_kwargs: dict = (
            {"max_probes_per_phase": max_probes_per_phase}
            if max_probes_per_phase is not None
            else {}
        )
        flow_kwargs.update(initial_state or {})
        self.flow = InterviewFlow(outline, llm_client, **flow_kwargs)
        self._turn_sink = turn_sink
        self._status_sink = status_sink
        self._completion_reported = False

    async def _record(self, speaker: str, text: str) -> None:
        if self._turn_sink and text.strip():
            await self._turn_sink(
                turn_id=f"turn_{uuid.uuid4().hex}",
                speaker=speaker,
                text=text.strip(),
                phase_index=self.phase_index,
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
        question = await self.generate_next_question(last_candidate_turn=None)
        await self._record("agent", question)
        await self.session.say(question)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        candidate_turn = last_text(chat_ctx)
        if candidate_turn:
            await self._record("candidate", candidate_turn)
        question = await self.generate_next_question(candidate_turn or None)
        await self._record("agent", question)
        yield question
        if (
            self.flow.completed
            and self._status_sink
            and not self._completion_reported
        ):
            self._completion_reported = True
            await self._status_sink("completing", reason="interview_flow_complete")
            await self._status_sink("completed", reason="closing_delivered")
