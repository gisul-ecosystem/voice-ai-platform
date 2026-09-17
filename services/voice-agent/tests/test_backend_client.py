from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from clients import backend_client


@pytest.mark.asyncio
async def test_lifecycle_writes_enable_safe_transport_retries(monkeypatch) -> None:
    request = AsyncMock()
    monkeypatch.setattr(backend_client, "request", request)

    await backend_client.report_session_status("ses_test", "live")
    await backend_client.record_session_turn(
        "ses_test",
        turn_id="turn_test",
        speaker="candidate",
        text="My answer",
        phase_index=0,
        sequence_number=1,
    )

    assert request.await_args_list[0].kwargs["retry_safe"] is True
    assert request.await_args_list[1].kwargs["retry_safe"] is True
