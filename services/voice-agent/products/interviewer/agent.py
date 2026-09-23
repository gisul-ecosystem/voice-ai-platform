"""LiveKit adapter for the provider-neutral interview flow."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable

from livekit.agents import Agent, ModelSettings, llm

from products.interviewer.brain_runtime import BrainSessionBridge
from products.interviewer.flow import CLOSING_MESSAGE, FALLBACK_OPENING, InterviewFlow
from voice_platform.chat import is_usable_candidate_turn, last_text

logger = logging.getLogger("voice-agent.interviewer")

CLARIFY_TURN = (
    "Sorry, I did not catch that. Please say a bit more, in a full sentence."
)
# Keep the room from sitting silent while the LLM or TTS stalls on the first line.
OPENING_LLM_TIMEOUT_SECONDS = float(os.getenv("OPENING_LLM_TIMEOUT_SECONDS", "6"))
OPENING_TTS_TIMEOUT_SECONDS = float(os.getenv("OPENING_TTS_TIMEOUT_SECONDS", "20"))


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
        difficulty: str | None = None,
        language: str | None = None,
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
        if difficulty:
            flow_kwargs["difficulty"] = difficulty
        if language:
            flow_kwargs["language"] = language
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
        self._opening_in_progress = False
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

    def _commit_local_opening(self, opening: str) -> None:
        """Record a local opening when the LLM stream never finished."""
        if self.flow.interviewer_turns:
            return
        self.flow.last_question_competency_id = None
        self.flow.last_question_intent = "opening"
        self.flow.last_question_depth = 1
        self.flow.last_question_claim_ids = []
        self.flow._remember_question(opening)

    async def _resolve_opening_speech(self) -> str:
        """Return opening text as soon as the LLM yields it, or fall back fast.

        Waiting for the entire stream generator (including repair / ledger work)
        before TTS left the room silent when the LLM stalled.
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _produce() -> None:
            try:
                async for chunk in self.flow.generate_next_question_stream(None):
                    text = (chunk or "").strip()
                    if text:
                        await queue.put(text)
            except Exception:
                logger.exception(
                    "opening_stream_failed",
                    extra={"event": "opening_stream_failed"},
                )
            finally:
                await queue.put(None)

        producer = asyncio.create_task(_produce())
        try:
            first = await asyncio.wait_for(
                queue.get(), timeout=max(2.0, OPENING_LLM_TIMEOUT_SECONDS)
            )
            if first:
                return first
        except asyncio.TimeoutError:
            logger.warning(
                "opening_llm_timeout",
                extra={
                    "event": "opening_llm_timeout",
                    "timeout_seconds": OPENING_LLM_TIMEOUT_SECONDS,
                },
            )
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
        except Exception:
            logger.exception(
                "opening_resolve_failed",
                extra={"event": "opening_resolve_failed"},
            )
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass

        opening = self.flow._fallback_opening() or FALLBACK_OPENING
        self._commit_local_opening(opening)
        return opening

    async def _speak_opening(self, opening: str) -> None:
        logger.info(
            "interviewer_speaking_opening",
            extra={"event": "interviewer_speaking_opening", "opening": opening},
        )
        await asyncio.wait_for(
            self.session.say(opening, allow_interruptions=False),
            timeout=max(5.0, OPENING_TTS_TIMEOUT_SECONDS),
        )
        logger.info(
            "interviewer_speaking_opening_done",
            extra={"event": "interviewer_speaking_opening_done"},
        )

    async def on_enter(self) -> None:
        if self._opened:
            # Rejoin/restore: do not re-speak the opening or double-write brain.
            return
        # Claim the opening slot before awaiting synthesis so a concurrent LLM
        # callback cannot schedule a second opening for the same room.
        self._opening_in_progress = True
        logger.info(
            "interviewer_on_enter_start",
            extra={"event": "interviewer_on_enter_start"},
        )
        try:
            opening = await self._resolve_opening_speech()
            await self._speak_opening(opening)
            self._opened = True
            self._last_agent_text = opening
            turn_id = await self._record("agent", opening)
            await self._persist_brain_after_exchange(
                speaker="agent",
                text=opening,
                turn_id=turn_id,
            )
        except Exception:
            logger.exception(
                "interviewer_opening_failed",
                extra={"event": "interviewer_opening_failed"},
            )
            try:
                fallback = self.flow._fallback_opening() or FALLBACK_OPENING
                self._commit_local_opening(fallback)
                await self._speak_opening(fallback)
                self._opened = True
                self._last_agent_text = fallback
                turn_id = await self._record("agent", fallback)
                await self._persist_brain_after_exchange(
                    speaker="agent",
                    text=fallback,
                    turn_id=turn_id,
                )
            except Exception:
                # Leave _opened False so llm_node can still try to open.
                logger.exception(
                    "interviewer_opening_fallback_failed",
                    extra={"event": "interviewer_opening_fallback_failed"},
                )
                self._opened = False
        finally:
            self._opening_in_progress = False

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list,
        model_settings: ModelSettings,
    ):
        candidate_turn = last_text(chat_ctx)
        if self._opening_in_progress or (self._opened and not candidate_turn):
            return
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
            question = self.flow._fallback_spoken_question(
                self.flow.last_policy_decision,
                last_turn=candidate_turn,
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
