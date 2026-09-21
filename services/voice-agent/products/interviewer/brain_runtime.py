"""Map InterviewFlow RAM state <-> durable 3-layer brain snapshots."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from clients.backend_client import (
    fetch_brain_state,
    put_brain_state,
    record_brain_answer,
    record_brain_question,
)
from clients.errors import ServiceUnavailableError

logger = logging.getLogger("voice-agent.aaptor")


def definition_id_for_session(
    session_id: str,
    context_id: str | None = None,
    *,
    explicit_definition_id: str | None = None,
) -> str:
    explicit = (explicit_definition_id or "").strip()
    if explicit:
        return explicit
    if context_id and len(context_id) >= 8:
        return f"idef_{context_id[-24:]}"
    return f"idef_pending_{session_id[-16:]}"


def flow_to_brain_state(
    *,
    session_id: str,
    definition_id: str,
    flow,
    state_version: int,
    active_question_id: str | None,
    asked_question_ids: list[str],
    started_monotonic: float,
) -> dict[str, Any]:
    section = "completed" if getattr(flow, "completed", False) else "competency_assessment"
    if not flow.candidate_turns:
        section = "opening"
    elif len(flow.candidate_turns) == 1 and flow.probe_count <= 1:
        section = "candidate_map"
    policy = getattr(flow, "last_policy_decision", None)
    phase = flow.current_phase() if hasattr(flow, "current_phase") else {}
    competency_id = (
        getattr(flow, "last_question_competency_id", None)
        or (getattr(policy, "competency_id", None) if policy else None)
        or phase.get("competency_id")
    )
    profile = getattr(flow, "candidate_profile", None) or {}
    claim_ids = [
        str(item.get("claim_id"))
        for item in (profile.get("claims") or [])
        if isinstance(item, dict) and item.get("claim_id")
    ]
    return {
        "session_id": session_id,
        "definition_id": definition_id,
        "state_version": max(0, state_version),
        "current_section": section,
        "phase_index": max(0, int(getattr(flow, "phase_index", 0))),
        "current_competency_id": competency_id,
        "current_depth": min(
            5,
            max(1, int(getattr(flow, "last_question_depth", 0) or flow.probe_count + 1)),
        ),
        "active_question_id": active_question_id,
        "asked_question_ids": list(asked_question_ids),
        "candidate_claim_ids": claim_ids,
        "coverage": dict(getattr(flow, "coverage", None) or {}),
        "consecutive_unusable_answers": max(
            0, int(getattr(flow, "consecutive_unusable", 0) or 0)
        ),
        "elapsed_seconds": max(0, int(time.monotonic() - started_monotonic)),
        "last_processed_turn_id": None,
        "next_action": (
            "CLOSE_INTERVIEW"
            if flow.completed
            else (getattr(policy, "action", None) if policy else None)
        ),
    }


def brain_bundle_to_initial_state(bundle: dict[str, Any] | None) -> dict[str, Any]:
    """Convert brain API payload into InterviewFlow constructor kwargs."""
    if not bundle or not isinstance(bundle, dict):
        return {}
    state = bundle.get("state") if isinstance(bundle.get("state"), dict) else {}
    questions = bundle.get("questions") if isinstance(bundle.get("questions"), list) else []
    answers = bundle.get("answers") if isinstance(bundle.get("answers"), list) else []

    interviewer_turns = [
        str(item.get("text") or "")
        for item in questions
        if isinstance(item, dict) and item.get("text")
    ]
    candidate_turns = [
        str(item.get("final_transcript") or "")
        for item in answers
        if isinstance(item, dict) and item.get("final_transcript")
    ]
    asked_question_ids = [
        str(item.get("question_id") or "")
        for item in questions
        if isinstance(item, dict) and item.get("question_id")
    ]
    active_question_id = state.get("active_question_id")
    if not active_question_id and asked_question_ids:
        active_question_id = asked_question_ids[-1]

    restored: dict[str, Any] = {
        "candidate_turns": candidate_turns,
        "interviewer_turns": interviewer_turns,
        "initial_phase_index": max(0, int(state.get("phase_index") or 0)),
        "initial_probe_count": max(0, int(state.get("current_depth") or 1) - 1),
        "initial_sequence_number": len(candidate_turns) + len(interviewer_turns),
        "brain_state_version": int(state.get("state_version") or 0),
        "brain_active_question_id": active_question_id,
        "brain_asked_question_ids": [qid for qid in asked_question_ids if qid],
        "initial_coverage": state.get("coverage") or {},
    }
    return restored


class BrainSessionBridge:
    """Persist question/answer/snapshot for one live session."""

    def __init__(
        self,
        *,
        session_id: str,
        definition_id: str,
        state_version: int = 0,
        active_question_id: str | None = None,
        asked_question_ids: list[str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.definition_id = definition_id
        self.state_version = max(0, state_version)
        self.active_question_id = active_question_id
        self.asked_question_ids = list(asked_question_ids or [])
        self._started = time.monotonic()
        self._pending_answer_turn_ids: list[str] = []

    async def on_agent_question(
        self,
        text: str,
        *,
        phase_index: int,
        competency_id: str | None = None,
        intent: str | None = None,
        depth: int | None = None,
        source_claim_ids: list[str] | None = None,
        prompt_version: str | None = None,
        definition_id: str | None = None,
        policy_action: str | None = None,
        validator_ok: bool | None = None,
        validator_reasons: list[str] | None = None,
        raw_model_output: str | None = None,
    ) -> str | None:
        question_id = f"q_{uuid.uuid4().hex[:16]}"
        try:
            await record_brain_question(
                self.session_id,
                question_id=question_id,
                text=text,
                intent=(intent or "live_question"),
                depth=min(5, max(1, int(depth if depth is not None else phase_index + 1))),
                competency_id=competency_id,
                source_claim_ids=list(source_claim_ids or []),
                status="spoken",
                prompt_version=prompt_version,
                definition_id=definition_id or self.definition_id,
                policy_action=policy_action,
                validator_ok=validator_ok,
                validator_reasons=list(validator_reasons or []),
                raw_model_output=raw_model_output,
            )
        except ServiceUnavailableError:
            logger.warning(
                "brain_question_persist_unavailable",
                extra={"event": "brain_question_persist_unavailable"},
            )
            return None
        self.active_question_id = question_id
        self.asked_question_ids.append(question_id)
        return question_id

    async def on_candidate_answer(
        self,
        text: str,
        *,
        turn_id: str,
        usable: bool | None = None,
        usability: str | None = None,
    ) -> None:
        if not self.active_question_id:
            return
        answer_id = f"a_{uuid.uuid4().hex[:16]}"
        resolved_usability = usability or "usable"
        resolved_usable = True if usable is None else bool(usable)
        if usability:
            resolved_usable = usability == "usable"
        try:
            await record_brain_answer(
                self.session_id,
                answer_id=answer_id,
                question_id=self.active_question_id,
                turn_ids=[turn_id],
                final_transcript=text,
                usable=resolved_usable,
                usability=resolved_usability,
            )
        except ServiceUnavailableError:
            logger.warning(
                "brain_answer_persist_unavailable",
                extra={"event": "brain_answer_persist_unavailable"},
            )
            return
        self._pending_answer_turn_ids = [turn_id]

    async def checkpoint(self, flow) -> None:
        self.state_version += 1
        payload = flow_to_brain_state(
            session_id=self.session_id,
            definition_id=self.definition_id,
            flow=flow,
            state_version=self.state_version,
            active_question_id=self.active_question_id,
            asked_question_ids=self.asked_question_ids,
            started_monotonic=self._started,
        )
        if self._pending_answer_turn_ids:
            payload["last_processed_turn_id"] = self._pending_answer_turn_ids[-1]
        try:
            await put_brain_state(self.session_id, payload)
        except ServiceUnavailableError:
            logger.warning(
                "brain_checkpoint_unavailable",
                extra={
                    "event": "brain_checkpoint_unavailable",
                    "state_version": self.state_version,
                },
            )
            # Allow local version to stay ahead; next successful write uses new version.
            return


def _is_not_found(exc: BaseException) -> bool:
    cause = getattr(exc, "__cause__", None)
    response = getattr(cause, "response", None)
    if response is not None and getattr(response, "status_code", None) == 404:
        return True
    return "404" in str(exc)


async def load_brain_initial_state(session_id: str) -> dict[str, Any]:
    try:
        bundle = await fetch_brain_state(session_id)
    except ServiceUnavailableError as exc:
        # 404 means first join — fall back to transcript restore.
        if _is_not_found(exc):
            return {}
        logger.warning(
            "brain_restore_unavailable",
            extra={"event": "brain_restore_unavailable"},
        )
        return {}
    return brain_bundle_to_initial_state(bundle)
