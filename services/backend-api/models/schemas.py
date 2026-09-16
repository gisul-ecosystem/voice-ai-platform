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


class InterviewPlanRequest(BaseModel):
    job_description: str = Field(min_length=1, max_length=100_000)
    resume_text: str = Field(min_length=1, max_length=100_000)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Test Candidate", min_length=1, max_length=120)
    product_id: Literal["interviewer", "customer-support"] = "interviewer"
    context_id: str | None = Field(default=None, min_length=16, max_length=128)
    invitation_token: str | None = Field(default=None, min_length=16, max_length=4096)


class CreateSessionResponse(BaseModel):
    room: str
    token: str
    livekit_url: str
    product_id: str
    session_id: str
    expires_at: datetime


class CreateInterviewContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_description: str = Field(min_length=1, max_length=100_000)
    resume_text: str = Field(min_length=1, max_length=100_000)


class CreateInterviewContextResponse(BaseModel):
    context_id: str
    expires_at: datetime


class InterviewContextResponse(BaseModel):
    context_id: str
    job_description: str
    resume_text: str


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=3, max_length=128)
    ttl_minutes: int = Field(default=60, ge=5, le=1_440)


class CreateInvitationResponse(BaseModel):
    invitation_token: str
    expires_at: datetime


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
