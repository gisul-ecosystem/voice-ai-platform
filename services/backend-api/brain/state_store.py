"""Three-layer interview brain state service.

Layer 1: worker RAM (outside this service)
Layer 2: Redis hot snapshot (db.redis_brain)
Layer 3: Mongo durable records (db.brain)
"""
from __future__ import annotations

from typing import Any

from db import brain as brain_db
from db import redis_brain
from models.brain import (
    InterviewAnswerRecord,
    InterviewBrainState,
    InterviewEvidenceRecord,
    InterviewQuestionRecord,
)


async def save_brain_state(state: InterviewBrainState) -> dict[str, Any]:
    """Persist durable snapshot then refresh hot cache."""
    durable = await brain_db.save_durable_snapshot(state)
    if durable == "conflict":
        return {"ok": False, "durable": durable, "hot": None}
    hot = redis_brain.put_hot_snapshot(
        state.session_id, state.model_dump(mode="python")
    )
    return {"ok": True, "durable": durable, "hot": hot}


async def load_brain_state(session_id: str) -> InterviewBrainState | None:
    """Prefer Redis hot snapshot; fall back to latest Mongo snapshot."""
    hot = redis_brain.get_hot_snapshot(session_id)
    if hot is not None:
        return InterviewBrainState.model_validate(hot)
    durable = await brain_db.latest_durable_snapshot(session_id)
    if durable is None:
        return None
    durable.pop("_id", None)
    state = InterviewBrainState.model_validate(durable)
    # Repopulate hot cache for subsequent fast reads.
    redis_brain.put_hot_snapshot(session_id, state.model_dump(mode="python"))
    return state


async def record_question(record: InterviewQuestionRecord) -> str:
    return await brain_db.upsert_question(record)


async def record_answer(record: InterviewAnswerRecord) -> str:
    return await brain_db.upsert_answer(record)


async def record_evidence(record: InterviewEvidenceRecord) -> str:
    return await brain_db.upsert_evidence(record)


async def session_memory_bundle(session_id: str) -> dict[str, Any]:
    state = await load_brain_state(session_id)
    return {
        "session_id": session_id,
        "state": state.model_dump(mode="python") if state else None,
        "questions": await brain_db.list_session_questions(session_id),
        "answers": await brain_db.list_session_answers(session_id),
        "evidence": await brain_db.list_session_evidence(session_id),
    }
