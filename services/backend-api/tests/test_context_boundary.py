from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from models.schemas import CreateInterviewContextRequest
from routers import interview_contexts


@pytest.mark.asyncio
async def test_context_creation_returns_only_opaque_reference(monkeypatch) -> None:
    async def fake_create(job_description: str, resume_text: str) -> dict:
        assert job_description == "Backend engineer"
        assert resume_text == "Python experience"
        return {
            "context_id": "ctx_1234567890123456",
            "expires_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr(interview_contexts.interviews, "create_context", fake_create)
    response = await interview_contexts.create_interview_context(
        CreateInterviewContextRequest(
            job_description="Backend engineer",
            resume_text="Python experience",
        )
    )

    assert response.context_id == "ctx_1234567890123456"
    assert not hasattr(response, "job_description")
    assert not hasattr(response, "resume_text")


@pytest.mark.asyncio
async def test_missing_context_is_not_disclosed(monkeypatch) -> None:
    async def missing(_context_id: str):
        return None

    monkeypatch.setattr(interview_contexts.interviews, "get_context", missing)
    with pytest.raises(HTTPException) as error:
        await interview_contexts.read_interview_context("ctx_missing")
    assert error.value.status_code == 404
