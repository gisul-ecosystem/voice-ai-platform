"""Pydantic models shared across the backend API."""
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime
import uuid


class InterviewPhase(BaseModel):
    name: str
    duration_minutes: int
    topics: list[str]
    source: Literal["resume", "jd", "generic"]


class InterviewOutline(BaseModel):
    phases: list[InterviewPhase]


class InterviewPlanRequest(BaseModel):
    job_description: str
    resume_text: str


class CreateSessionRequest(BaseModel):
    identity: str = "test-candidate"
    name: str = "Test Candidate"
    room: str | None = None
    job_description: str | None = None
    resume_text: str | None = None
    agent_name: Literal["aaptor", "racko"] = "aaptor"
    ttl_minutes: int | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
    stt_provider: str | None = None
    stt_api_key: str | None = None
    tts_provider: str | None = None
    tts_api_key: str | None = None


class CreateSessionResponse(BaseModel):
    room: str
    token: str
    livekit_url: str
    llm_provider: str | None = None
    stt_provider: str | None = None
    tts_provider: str | None = None
    llm_api_key_set: bool = False
    stt_api_key_set: bool = False
    tts_api_key_set: bool = False


class Turn(BaseModel):
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    speaker: Literal["candidate", "agent"]
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InterviewSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str
    role_id: str
    outline: InterviewOutline | None = None
    turns: list[Turn] = []
    status: Literal["scheduled", "in_progress", "completed"] = "scheduled"
    created_at: datetime = Field(default_factory=datetime.utcnow)
