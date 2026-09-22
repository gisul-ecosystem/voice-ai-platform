from __future__ import annotations

import pytest
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db import interviews
from db.mongo import MemoryDatabase
from models.schemas import SessionStatusRequest, SessionTurnRequest
from routers import session_events


@pytest.mark.asyncio
async def test_turn_database_failure_returns_retryable_error(monkeypatch) -> None:
    async def fail(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session_events.interviews, "append_turn", fail)

    with pytest.raises(HTTPException) as raised:
        await session_events.record_session_turn(
            "ses_test",
            SessionTurnRequest(
                turn_id="turn_test",
                speaker="candidate",
                text="My answer",
                phase_index=0,
                sequence_number=1,
            ),
        )

    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_memory_fallback_preserves_lifecycle_events(monkeypatch) -> None:
    db = MemoryDatabase()
    monkeypatch.setattr(session_events.interviews, "get_db", lambda: db)
    await db.interview_sessions.insert_one(
        {"_id": "ses_test", "status": "live", "events": []}
    )

    assert await session_events.interviews.transition_session(
        "ses_test",
        expected=("live",),
        status="completed",
    )

    session = await db.interview_sessions.find_one({"_id": "ses_test"})
    assert session is not None
    assert session["events"][-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_lifecycle_transition_returns_conflict(monkeypatch) -> None:
    async def unchanged(*_args, **_kwargs):
        return False

    async def current(_session_id):
        return {"_id": "ses_test", "status": "joining", "turns": []}

    monkeypatch.setattr(session_events.interviews, "transition_session", unchanged)
    monkeypatch.setattr(session_events.interviews, "get_session", current)

    with pytest.raises(HTTPException) as raised:
        await session_events.update_session_status(
            "ses_test",
            SessionStatusRequest(status="completed"),
        )

    assert raised.value.status_code == 409


@pytest.mark.asyncio
async def test_abandoned_session_generates_evidence_limited_scorecard(monkeypatch) -> None:
    generated: list[str] = []

    async def transition(*_args, **_kwargs):
        return True

    async def generate(session_id: str):
        generated.append(session_id)
        return {"session_id": session_id, "overall_recommendation": "insufficient_evidence"}

    monkeypatch.setattr(session_events.interviews, "transition_session", transition)
    monkeypatch.setattr(session_events.scoring_service, "generate_and_store_scorecard", generate)

    await session_events.update_session_status(
        "ses_abandoned_scorecard",
        SessionStatusRequest(status="abandoned", reason="worker_shutdown"),
    )

    assert generated == ["ses_abandoned_scorecard"]


@pytest.mark.asyncio
async def test_concurrent_duplicate_turn_is_idempotent(monkeypatch) -> None:
    turn = {
        "turn_id": "turn_test",
        "speaker": "candidate",
        "text": "My answer",
        "phase_index": 0,
        "sequence_number": 1,
        "is_final": True,
    }

    class Sessions:
        async def find_one(self, *_args, **_kwargs):
            return {"_id": "ses_test"}

    class Turns:
        calls = 0

        async def find_one(self, *_args, **_kwargs):
            self.calls += 1
            return None if self.calls == 1 else {**turn, "session_id": "ses_test"}

        async def insert_one(self, _document):
            raise DuplicateKeyError("duplicate")

    class Db:
        interview_sessions = Sessions()
        interview_turns = Turns()

    monkeypatch.setattr(interviews, "get_db", lambda: Db())

    assert await interviews.append_turn("ses_test", turn) == "duplicate"
