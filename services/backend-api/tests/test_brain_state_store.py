"""Three-layer brain store: Redis hot + Mongo durable + session isolation."""
from __future__ import annotations

import pytest

from brain import state_store
from db import redis_brain
from db.mongo import MemoryDatabase, set_fallback_mode
from models.brain import (
    InterviewAnswerRecord,
    InterviewBrainState,
    InterviewEvidenceRecord,
    InterviewQuestionRecord,
)


@pytest.fixture(autouse=True)
def memory_db(monkeypatch):
    set_fallback_mode(True)
    db = MemoryDatabase()
    monkeypatch.setattr("db.brain.get_db", lambda: db)
    monkeypatch.setattr("db.mongo.get_db", lambda: db)
    redis_brain.reset_redis_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    yield db
    redis_brain.reset_redis_for_tests()
    set_fallback_mode(False)


def _state(session_id: str, version: int = 1) -> InterviewBrainState:
    return InterviewBrainState(
        session_id=session_id,
        definition_id="idef_test123456",
        state_version=version,
        current_section="competency_assessment",
        current_competency_id="problem_solving",
        current_depth=2,
        active_question_id="q_1",
        asked_question_ids=["q_1"],
        consecutive_unusable_answers=0,
        elapsed_seconds=120,
    )


@pytest.mark.asyncio
async def test_hot_and_durable_snapshot_roundtrip() -> None:
    saved = await state_store.save_brain_state(_state("ses_alpha"))
    assert saved["ok"] is True
    assert saved["hot"] == "memory"
    assert saved["durable"] == "created"

    loaded = await state_store.load_brain_state("ses_alpha")
    assert loaded is not None
    assert loaded.session_id == "ses_alpha"
    assert loaded.state_version == 1
    assert loaded.active_question_id == "q_1"


@pytest.mark.asyncio
async def test_sessions_are_isolated_in_hot_and_durable_layers() -> None:
    await state_store.save_brain_state(_state("ses_alpha01", version=1))
    await state_store.save_brain_state(
        InterviewBrainState(
            session_id="ses_bravo01",
            definition_id="idef_test123456",
            state_version=1,
            current_section="opening",
            active_question_id="q_other",
        )
    )

    a = await state_store.load_brain_state("ses_alpha01")
    b = await state_store.load_brain_state("ses_bravo01")
    assert a is not None and b is not None
    assert a.active_question_id == "q_1"
    assert b.active_question_id == "q_other"
    assert redis_brain.get_hot_snapshot("ses_alpha01")["session_id"] == "ses_alpha01"
    assert redis_brain.get_hot_snapshot("ses_bravo01")["session_id"] == "ses_bravo01"


@pytest.mark.asyncio
async def test_version_conflict_is_detected() -> None:
    await state_store.save_brain_state(_state("ses_conflict", version=3))
    again = await state_store.save_brain_state(
        InterviewBrainState(
            session_id="ses_conflict",
            definition_id="idef_test123456",
            state_version=3,
            current_section="closing",
            active_question_id="q_changed",
        )
    )
    assert again["ok"] is False
    assert again["durable"] == "conflict"


@pytest.mark.asyncio
async def test_question_answer_evidence_are_session_scoped() -> None:
    assert (
        await state_store.record_question(
            InterviewQuestionRecord(
                question_id="q_1001",
                session_id="ses_memory01",
                competency_id="problem_solving",
                intent="establish_context",
                depth=1,
                text="What problem did you solve?",
                status="spoken",
            )
        )
        == "created"
    )
    assert (
        await state_store.record_answer(
            InterviewAnswerRecord(
                answer_id="a_1001",
                question_id="q_1001",
                session_id="ses_memory01",
                turn_ids=["turn_1"],
                final_transcript="I fixed a timeout by adding retries.",
                usable=True,
                usability="usable",
            )
        )
        == "created"
    )
    assert (
        await state_store.record_evidence(
            InterviewEvidenceRecord(
                evidence_id="ev_1001",
                session_id="ses_memory01",
                competency_id="problem_solving",
                question_id="q_1001",
                turn_ids=["turn_1"],
                claim="Added retries for timeouts",
                strength="partial",
                confidence=0.8,
            )
        )
        == "created"
    )

    bundle = await state_store.session_memory_bundle("ses_memory01")
    assert len(bundle["questions"]) == 1
    assert len(bundle["answers"]) == 1
    assert len(bundle["evidence"]) == 1
    assert bundle["questions"][0]["session_id"] == "ses_memory01"

    other = await state_store.session_memory_bundle("ses_other01")
    assert other["questions"] == []
    assert other["answers"] == []
    assert other["evidence"] == []


def test_redis_key_is_namespaced_by_session() -> None:
    assert redis_brain.brain_key("ses_123") == "interview:brain:ses_123"
    with pytest.raises(ValueError):
        redis_brain.brain_key("")


def test_hot_snapshot_rejects_mismatched_session_payload() -> None:
    with pytest.raises(ValueError):
        redis_brain.put_hot_snapshot(
            "ses_1",
            {"session_id": "ses_2", "state_version": 1},
        )
