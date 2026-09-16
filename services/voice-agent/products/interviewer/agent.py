"""LiveKit adapter for the provider-neutral interview flow."""
from __future__ import annotations

from livekit.agents import Agent, ModelSettings, llm

from products.interviewer.flow import InterviewFlow
from voice_platform.chat import last_text


class AaptorAgent(Agent):
    """Aaptor's LiveKit surface; interview state lives in InterviewFlow."""

    def __init__(self, outline: dict, llm_client) -> None:
        super().__init__(
            instructions=(
                "You are Aaptor, an AI interviewer. Ask one concise spoken question "
                "at a time. Do not use markdown."
            )
        )
        self.flow = InterviewFlow(outline, llm_client)

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
        await self.session.say(question)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        candidate_turn = last_text(chat_ctx)
        question = await self.generate_next_question(candidate_turn or None)
        yield question
