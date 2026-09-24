from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.schemas import (
    CreateScheduledInterviewRequest,
    InterviewSetupConfig,
    InvitationPreviewRequest,
    RecordConsentRequest,
)
from routers import scheduled_interviews


def _setup() -> InterviewSetupConfig:
    return InterviewSetupConfig(
        title="Backend interview",
        role="Backend Engineer",
        seniority="mid",
        difficulty="applied",
        durationMinutes=30,
        language="English",
        competencies=["Problem solving", "Python"],
        maxProbesPerPhase=2,
        monitoringEnabled=True,
        recordingEnabled=False,
    )


def test_external_interview_id_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        CreateScheduledInterviewRequest(
            source_product_id="reference-demo",
            external_interview_id="   ",
            candidate_name="Priya",
            candidate_email="priya@example.com",
            starts_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            timezone="Asia/Kolkata",
            job_description="Build backend services",
            resume_text="Five years of Python",
            interview_setup=_setup(),
        )


@pytest.mark.asyncio
async def test_schedule_creates_previewable_invitation(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    captured: dict = {}

    async def create_context(*_args, **_kwargs):
        return {
            "context_id": "ctx_1234567890123456",
            "expires_at": now,
            "definition_id": "idef_scheduled_test01",
        }

    async def store_invitation(**_kwargs):
        return None

    async def create_schedule(document):
        captured.update(document)

    class _Published:
        definition_id = "idef_scheduled_test01"

    async def publish_and_store(**_kwargs):
        return _Published()

    monkeypatch.setenv("INTERVIEW_INVITATION_SECRET", "test-secret")
    monkeypatch.setattr(
        scheduled_interviews.interviews, "create_context", create_context
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews, "store_invitation", store_invitation
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews,
        "create_scheduled_interview",
        create_schedule,
    )
    monkeypatch.setattr(
        scheduled_interviews, "publish_and_store", publish_and_store
    )

    created = await scheduled_interviews.create_scheduled_interview(
        CreateScheduledInterviewRequest(
            source_product_id="reference-demo",
            candidate_name="Priya",
            candidate_email="priya@example.com",
            starts_at=now + timedelta(minutes=10),
            timezone="Asia/Kolkata",
            join_early_minutes=15,
            late_grace_minutes=120,
            job_description="Build backend services",
            resume_text="Five years of Python",
            interview_setup=_setup(),
        )
    )
    assert created.status == "scheduled"
    assert created.definition_id == "idef_scheduled_test01"
    assert captured["definition_id"] == "idef_scheduled_test01"
    assert captured["candidate_email"] == "priya@example.com"
    assert captured["invitation_token"] == created.invitation_token
    assert captured["external_interview_id"].startswith("ext_")
    assert captured["join_not_before"] <= now

    async def find_schedule(_invitation_id):
        return captured

    monkeypatch.setattr(
        scheduled_interviews.interviews,
        "get_scheduled_interview_by_invitation",
        find_schedule,
    )
    preview = await scheduled_interviews.preview_invitation(
        InvitationPreviewRequest(invitation_token=created.invitation_token)
    )
    assert preview.status == "ready"
    assert preview.role == "Backend Engineer"
    assert preview.monitoring_enabled is True


@pytest.mark.asyncio
async def test_schedule_rolls_back_context_when_invitation_write_fails(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    rolled_back: dict = {}

    async def create_context(*_args, **_kwargs):
        return {"context_id": "ctx_1234567890123456", "expires_at": now}

    async def store_invitation(**_kwargs):
        raise RuntimeError("database unavailable")

    async def rollback(**kwargs):
        rolled_back.update(kwargs)

    class _Published:
        definition_id = "idef_scheduled_test01"

    async def publish_and_store(**_kwargs):
        return _Published()

    monkeypatch.setenv("INTERVIEW_INVITATION_SECRET", "test-secret")
    monkeypatch.setattr(
        scheduled_interviews.interviews, "create_context", create_context
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews, "store_invitation", store_invitation
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews, "rollback_schedule_artifacts", rollback
    )
    monkeypatch.setattr(
        scheduled_interviews, "publish_and_store", publish_and_store
    )

    with pytest.raises(RuntimeError):
        await scheduled_interviews.create_scheduled_interview(
            CreateScheduledInterviewRequest(
                source_product_id="reference-demo",
                candidate_name="Priya",
                candidate_email="priya@example.com",
                starts_at=now + timedelta(minutes=10),
                timezone="Asia/Kolkata",
                job_description="Build backend services",
                resume_text="Five years of Python",
                interview_setup=_setup(),
            )
        )

    assert rolled_back["context_id"] == "ctx_1234567890123456"
    assert rolled_back["invitation_id"]


@pytest.mark.asyncio
async def test_preview_normalizes_legacy_naive_mongo_datetimes(monkeypatch) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stored = {
        "_id": "int_legacy",
        "status": "scheduled",
        "candidate_name": "Priya",
        "starts_at": now,
        "timezone": "UTC",
        "join_not_before": now - timedelta(minutes=1),
        "join_closes_at": now + timedelta(minutes=30),
        "interview_setup": _setup().model_dump(mode="python"),
    }

    async def preview(_token):
        return {"interview_id": "int_legacy"}, stored

    monkeypatch.setattr(scheduled_interviews, "_preview", preview)

    result = await scheduled_interviews.preview_invitation(
        InvitationPreviewRequest(invitation_token="x" * 16)
    )

    assert result.status == "ready"
    assert result.starts_at.tzinfo is timezone.utc
    assert result.join_not_before.tzinfo is timezone.utc
    assert result.join_closes_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_required_monitoring_consent_is_persisted(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    stored = {
        "_id": "int_test",
        "status": "scheduled",
        "interview_setup": _setup().model_dump(mode="python"),
    }
    invitation = {
        "jti": "inv_test",
        "interview_id": "int_test",
        "context_id": "ctx_test",
        "candidate_id": "candidate_test",
    }
    persisted: dict = {}

    async def preview(_token):
        return invitation, stored

    async def record(_invitation_id, consent):
        persisted.update(consent)
        return True

    monkeypatch.setattr(scheduled_interviews, "_preview", preview)
    monkeypatch.setattr(
        scheduled_interviews.interviews, "record_candidate_consent", record
    )
    response = await scheduled_interviews.record_consent(
        RecordConsentRequest(
            invitation_token="x" * 16,
            ai_interview=True,
            transcription=True,
            monitoring=True,
            recording=False,
        )
    )
    assert response.status_code == 204
    assert persisted["monitoring"] is True
    assert persisted["recorded_at"] >= now


@pytest.mark.asyncio
async def test_duplicate_external_id_returns_conflict_and_rolls_back(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    rolled_back: dict = {}

    async def create_context(*_args, **_kwargs):
        return {"context_id": "ctx_1234567890123456", "expires_at": now}

    async def store_invitation(**_kwargs):
        return None

    async def create_schedule(_document):
        raise scheduled_interviews.interviews.ExternalInterviewConflictError

    async def rollback(**kwargs):
        rolled_back.update(kwargs)

    class _Published:
        definition_id = "idef_scheduled_test01"

    async def publish_and_store(**_kwargs):
        return _Published()

    monkeypatch.setenv("INTERVIEW_INVITATION_SECRET", "test-secret")
    monkeypatch.setattr(
        scheduled_interviews.interviews, "create_context", create_context
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews, "store_invitation", store_invitation
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews,
        "create_scheduled_interview",
        create_schedule,
    )
    monkeypatch.setattr(
        scheduled_interviews.interviews, "rollback_schedule_artifacts", rollback
    )
    monkeypatch.setattr(
        scheduled_interviews, "publish_and_store", publish_and_store
    )

    with pytest.raises(HTTPException) as raised:
        await scheduled_interviews.create_scheduled_interview(
            CreateScheduledInterviewRequest(
                source_product_id="reference-demo",
                external_interview_id="external-123",
                candidate_name="Priya",
                candidate_email="priya@example.com",
                starts_at=now + timedelta(minutes=10),
                timezone="Asia/Kolkata",
                job_description="Build backend services",
                resume_text="Five years of Python",
                interview_setup=_setup(),
            )
        )

    assert raised.value.status_code == 409
    assert rolled_back["context_id"] == "ctx_1234567890123456"
    assert rolled_back["invitation_id"].startswith("inv_")


@pytest.mark.asyncio
async def test_list_interviews_by_definition_id(monkeypatch) -> None:
    now = datetime.now(timezone.utc)

    async def list_rows(definition_id: str, *, limit: int = 50):
        assert definition_id == "idef_list_hub_01"
        assert limit == 50
        return [
            {
                "_id": "int_newest",
                "definition_id": definition_id,
                "candidate_name": "Asha",
                "candidate_email": "asha@example.com",
                "status": "scheduled",
                "starts_at": now,
                "invitation_token": "tok.newest",
                "created_at": now,
            },
            {
                "_id": "int_old",
                "definition_id": definition_id,
                "candidate_name": "Ravi",
                "candidate_email": "ravi@example.com",
                "status": "scheduled",
                "starts_at": now - timedelta(days=1),
                "invitation_token": None,
                "created_at": now - timedelta(days=1),
            },
        ]

    monkeypatch.setattr(
        scheduled_interviews.interviews,
        "list_scheduled_interviews_by_definition",
        list_rows,
    )
    listed = await scheduled_interviews.list_scheduled_interviews(
        definition_id="idef_list_hub_01"
    )
    assert len(listed.items) == 2
    assert listed.items[0].interview_id == "int_newest"
    assert listed.items[0].candidate_path == "/interview/invite/tok.newest"
    assert listed.items[1].candidate_path is None
    assert listed.items[1].invitation_token is None


@pytest.mark.asyncio
async def test_list_interviews_requires_definition_id() -> None:
    with pytest.raises(HTTPException) as raised:
        await scheduled_interviews.list_scheduled_interviews(definition_id="short")
    assert raised.value.status_code == 422
