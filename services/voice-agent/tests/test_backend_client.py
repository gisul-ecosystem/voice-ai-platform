from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from clients import backend_client


@pytest.mark.asyncio
async def test_lifecycle_writes_enable_safe_transport_retries(monkeypatch) -> None:
    response = MagicMock()
    response.json.return_value = {}
    request = AsyncMock(return_value=response)
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
    await backend_client.put_brain_state(
        "ses_test01",
        {
            "session_id": "ses_test01",
            "definition_id": "idef_pending_test01",
            "state_version": 1,
            "current_section": "opening",
        },
    )
    await backend_client.record_brain_question(
        "ses_test01",
        question_id="q_test01",
        text="What did you build?",
    )

    assert request.await_args_list[0].kwargs["retry_safe"] is True
    assert request.await_args_list[1].kwargs["retry_safe"] is True
    assert request.await_args_list[2].kwargs["retry_safe"] is True
    assert request.await_args_list[3].kwargs["retry_safe"] is True
    assert "/brain" in request.await_args_list[2].args[2]
    assert "/brain/questions" in request.await_args_list[3].args[2]
