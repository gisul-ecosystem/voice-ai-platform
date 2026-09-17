from __future__ import annotations

import pytest
from fastapi import HTTPException

from db.mongo import MemoryDatabase
from models.schemas import SessionTurnRequest
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
