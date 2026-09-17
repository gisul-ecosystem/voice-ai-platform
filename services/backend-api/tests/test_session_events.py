from __future__ import annotations

import pytest
from fastapi import HTTPException

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
async def test_completed_status_durably_enqueues_scorecard(monkeypatch) -> None:
    enqueued: list[str] = []

    async def transition(*_args, **_kwargs):
        return True

    async def enqueue(session_id: str):
        enqueued.append(session_id)

    monkeypatch.setattr(session_events.interviews, "transition_session", transition)
    monkeypatch.setattr(session_events.interviews, "enqueue_scorecard", enqueue)

    response = await session_events.update_session_status(
        "ses_test",
        SessionStatusRequest(status="completed"),
    )

    assert response.status_code == 204
    assert enqueued == ["ses_test"]
