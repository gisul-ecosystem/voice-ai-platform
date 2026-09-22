"""Pending turn flush keeps transcript persistence ordered under backend blips."""
from __future__ import annotations

import pytest

from clients.errors import ServiceUnavailableError
from products.interviewer.worker import flush_pending_session_turns


@pytest.mark.asyncio
async def test_flush_pending_session_turns_retries_queued_items(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_record(session_id: str, **turn) -> None:
        assert session_id == "sess_1"
        calls.append(str(turn["turn_id"]))
        if turn["turn_id"] == "turn_a" and calls.count("turn_a") == 1:
            raise ServiceUnavailableError("backend-api", "blip")

    monkeypatch.setattr(
        "products.interviewer.worker.record_session_turn",
        _fake_record,
    )
    pending = [
        {
            "turn_id": "turn_a",
            "speaker": "candidate",
            "text": "hello",
            "phase_index": 0,
            "sequence_number": 1,
        }
    ]
    assert (
        await flush_pending_session_turns("sess_1", pending, reason="first")
    ) is False
    assert pending[0]["turn_id"] == "turn_a"

    pending.append(
        {
            "turn_id": "turn_b",
            "speaker": "agent",
            "text": "hi",
            "phase_index": 0,
            "sequence_number": 2,
        }
    )
    assert (
        await flush_pending_session_turns("sess_1", pending, reason="retry")
    ) is True
    assert pending == []
    assert calls == ["turn_a", "turn_a", "turn_b"]
