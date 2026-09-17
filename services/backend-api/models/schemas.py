"""Pydantic models shared across the backend API."""
from datetime import datetime, timezone
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field


class InterviewPhase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=1, le=60)
    topics: list[str] = Field(min_length=1, max_length=20)
    source: Literal["resume", "jd", "generic"]


class InterviewOutline(BaseModel):
    phases: list[InterviewPhase] = Field(min_length=1, max_length=12)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Test Candidate", min_length=1, max_length=120)
    product_id: Literal["interviewer", "customer-support"] = "interviewer"
    context_id: str | None = Field(default=None, min_length=16, max_length=128)
    invitation_token: str | None = Field(default=None, min_length=16, max_length=4096)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class CreateSessionResponse(BaseModel):
    room: str
    token: str
    livekit_url: str
    product_id: str
    session_id: str
    expires_at: datetime


class InterviewSetupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    role: str = Field(min_length=2, max_length=160)
    seniority: Literal["intern", "junior", "mid", "senior", "lead"]
    difficulty: Literal["foundational", "applied", "diagnostic", "strategic"]
    durationMinutes: Literal[15, 30, 45] = 30
    language: str = Field(min_length=2, max_length=32)
    competencies: list[str] = Field(min_length=1, max_length=12)
    maxProbesPerPhase: int = Field(ge=0, le=3)
    monitoringEnabled: bool = True
    recordingEnabled: bool = False


class InterviewPlanRequest(BaseModel):
    job_description: str = Field(min_length=1, max_length=100_000)
    resume_text: str = Field(min_length=1, max_length=100_000)
    interview_setup: InterviewSetupConfig | None = None


class CreateInterviewContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_description: str = Field(min_length=1, max_length=100_000)
    resume_text: str = Field(min_length=1, max_length=100_000)
    interview_setup: InterviewSetupConfig | None = None


class CreateInterviewContextResponse(BaseModel):
    context_id: str
    expires_at: datetime


class InterviewContextResponse(BaseModel):
    context_id: str
    job_description: str
    resume_text: str
    interview_setup: InterviewSetupConfig | None = None


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=3, max_length=128)
    ttl_minutes: int = Field(default=60, ge=5, le=1_440)


class CreateInvitationResponse(BaseModel):
    invitation_token: str
    expires_at: datetime


class CreateScheduledInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_product_id: str = Field(min_length=2, max_length=64)
    external_interview_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^\S(?:.*\S)?$",
    )
    candidate_name: str = Field(min_length=1, max_length=120)
    candidate_email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    starts_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    join_early_minutes: int = Field(default=15, ge=0, le=120)
    late_grace_minutes: int = Field(default=15, ge=0, le=120)
    job_description: str = Field(min_length=1, max_length=100_000)
    resume_text: str = Field(min_length=1, max_length=100_000)
    interview_setup: InterviewSetupConfig


class CreateScheduledInterviewResponse(BaseModel):
    interview_id: str
    invitation_token: str
    status: Literal["scheduled"]
    starts_at: datetime


class InvitationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_token: str = Field(min_length=16, max_length=4096)


class InvitationPreviewResponse(BaseModel):
    interview_id: str
    candidate_name: str
    title: str
    role: str
    starts_at: datetime
    timezone: str
    duration_minutes: int
    join_not_before: datetime
    join_closes_at: datetime
    monitoring_enabled: bool
    recording_enabled: bool
    status: str


class RecordConsentRequest(InvitationPreviewRequest):
    ai_interview: bool
    transcription: bool
    monitoring: bool
    recording: bool
    policy_version: str = Field(default="2026-09-01", max_length=32)


class SessionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["live", "completing", "completed", "failed", "abandoned"]
    reason: str | None = Field(default=None, max_length=200)


class SessionTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=8, max_length=128)
    speaker: Literal["candidate", "agent"]
    text: str = Field(min_length=1, max_length=20_000)
    phase_index: int = Field(ge=0, le=100)
    sequence_number: int = Field(ge=1)
    is_final: bool = True
    language: str | None = Field(default=None, max_length=32)
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Turn(BaseModel):
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    speaker: Literal["candidate", "agent"]
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InterviewSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str
    role_id: str
    outline: InterviewOutline | None = None
    turns: list[Turn] = Field(default_factory=list)
    status: Literal[
        "scheduled",
        "ready",
        "joining",
        "live",
        "completing",
        "completed",
        "failed",
        "expired",
        "abandoned",
    ] = "scheduled"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
