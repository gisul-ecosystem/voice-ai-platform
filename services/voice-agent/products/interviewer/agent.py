"""LiveKit adapter for the provider-neutral interview flow."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from livekit.agents import Agent, ModelSettings, llm

from products.interviewer.brain_runtime import BrainSessionBridge
from products.interviewer.flow import CLOSING_MESSAGE, FALLBACK_FOLLOWUP, InterviewFlow
from voice_platform.chat import is_usable_candidate_turn, last_text

CLARIFY_TURN = (
    "Sorry, I did not catch that. Please say a bit more, in a full sentence."
)


class AaptorAgent(Agent):
    """LiveKit surface; interview state lives in InterviewFlow + optional brain bridge."""

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
        brain_bridge: BrainSessionBridge | None = None,
        interview_definition: dict | None = None,
        candidate_profile: dict | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are a professional structured interviewer. A policy engine "
                "already chose the evidence and depth for this turn. Phrase exactly "
                "one spoken question. Do not invent employers, projects, or skills. "
                "Do not mention phases, probes, or scores."
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
        if interview_definition is not None:
            flow_kwargs["interview_definition"] = interview_definition
        if candidate_profile is not None:
            flow_kwargs["candidate_profile"] = candidate_profile
        restored_state = dict(initial_state or {})
        self._sequence_number = int(restored_state.pop("initial_sequence_number", 0))
        # Brain metadata is not InterviewFlow constructor input.
        restored_state.pop("brain_state_version", None)
        restored_state.pop("brain_active_question_id", None)
        restored_state.pop("brain_asked_question_ids", None)
        flow_kwargs.update(restored_state)
        self.flow = InterviewFlow(outline, llm_client, **flow_kwargs)
        self._turn_sink = turn_sink
        self._status_sink = status_sink
        self._brain = brain_bridge
        self._completion_reported = False
        # Mid-session restore: any prior turn means opening already happened.
        self._opened = bool(self.flow.candidate_turns or self.flow.interviewer_turns)
        self._last_agent_text = (
            self.flow.interviewer_turns[-1] if self.flow.interviewer_turns else ""
        )

    async def _record(self, speaker: str, text: str) -> str | None:
        if not text.strip():
            return None
        turn_id = f"turn_{uuid.uuid4().hex}"
        if self._turn_sink:
            self._sequence_number += 1
            await self._turn_sink(
                turn_id=turn_id,
                speaker=speaker,
                text=text.strip(),
                phase_index=self.phase_index,
                sequence_number=self._sequence_number,
            )
        return turn_id

    async def _persist_brain_after_exchange(
        self,
        *,
        speaker: str,
        text: str,
        turn_id: str | None,
    ) -> None:
        if self._brain is None or not text.strip():
            return
        if speaker == "candidate" and turn_id:
            await self._brain.on_candidate_answer(
                text.strip(),
                turn_id=turn_id,
                usability=getattr(self.flow, "last_answer_usability", "usable"),
                answer_evaluation=getattr(self.flow, "last_answer_evaluation", None),
            )
        elif speaker == "agent":
            await self._brain.on_agent_question(
                text.strip(),
                phase_index=self.phase_index,
                competency_id=getattr(self.flow, "last_question_competency_id", None),
                intent=getattr(self.flow, "last_question_intent", None),
                depth=getattr(self.flow, "last_question_depth", None),
                source_claim_ids=getattr(self.flow, "last_question_claim_ids", None),
                prompt_version=getattr(self.flow, "_prompt_version", lambda: None)(),
                definition_id=self._brain.definition_id,
                policy_action=(
                    getattr(getattr(self.flow, "last_policy_decision", None), "action", None)
                ),
                validator_ok=getattr(self.flow, "last_validator_ok", None),
                validator_reasons=getattr(self.flow, "last_validator_reasons", None),
                raw_model_output=getattr(self.flow, "last_raw_model_output", None),
            )
        await self._brain.checkpoint(self.flow)

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
        if self._opened:
            # Rejoin/restore: do not re-speak the opening or double-write brain.
            return
        parts: list[str] = []
        async for chunk in self.flow.generate_next_question_stream(None):
            parts.append(chunk)
        opening = "".join(parts).strip() or self.flow._fallback_opening()
        await self.session.say(opening, allow_interruptions=False)
        self._opened = True
        self._last_agent_text = opening
        turn_id = await self._record("agent", opening)
        await self._persist_brain_after_exchange(
            speaker="agent",
            text=opening,
            turn_id=turn_id,
        )

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        candidate_turn = last_text(chat_ctx)
        opening = not self._opened
        candidate_brain_turn_id = None
        if opening:
            self._opened = True
            candidate_turn = None
        elif not is_usable_candidate_turn(
            candidate_turn,
            self._last_agent_text,
            min_words=1 if not self.flow.candidate_turns else 3,
        ):
            # Echo / noise / too-short STT must not pollute durable transcript or scoring.
            # Still ask for a clearer answer so the live session recovers.
            yield CLARIFY_TURN
            self._last_agent_text = CLARIFY_TURN
            turn_id = await self._record("agent", CLARIFY_TURN)
            await self._persist_brain_after_exchange(
                speaker="agent",
                text=CLARIFY_TURN,
                turn_id=turn_id,
            )
            return
        elif candidate_turn:
            turn_id = await self._record("candidate", candidate_turn)
            candidate_brain_turn_id = turn_id
        parts: list[str] = []
        async for chunk in self.flow.generate_next_question_stream(candidate_turn):
            parts.append(chunk)
            yield chunk
        question = "".join(parts).strip()
        if (
            question.endswith(CLOSING_MESSAGE)
            and question != CLOSING_MESSAGE
        ):
            prelude = question[: -len(CLOSING_MESSAGE)].strip()
            if prelude:
                self._last_agent_text = prelude
                turn_id = await self._record("agent", prelude)
                await self._persist_brain_after_exchange(
                    speaker="agent",
                    text=prelude,
                    turn_id=turn_id,
                )
            question = CLOSING_MESSAGE
        if not question:
            question = (
                self.flow._fallback_spoken_question(
                    self.flow.last_policy_decision,
                    last_turn=candidate_turn,
                )
                if not self.flow._uses_legacy_decision_flow()
                else FALLBACK_FOLLOWUP
            )
            yield question
        if candidate_turn and candidate_brain_turn_id:
            await self._persist_brain_after_exchange(
                speaker="candidate",
                text=candidate_turn,
                turn_id=candidate_brain_turn_id,
            )
        if question:
            self._last_agent_text = question
            turn_id = await self._record("agent", question)
            await self._persist_brain_after_exchange(
                speaker="agent",
                text=question,
                turn_id=turn_id,
            )
        if (
            self.flow.completed
            and self._status_sink
            and not self._completion_reported
        ):
            self._completion_reported = True
            await self._status_sink("completing", reason="interview_flow_complete")
            await self._status_sink("completed", reason="closing_delivered")
