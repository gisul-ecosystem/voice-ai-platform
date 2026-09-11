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
