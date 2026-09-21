"""Controlled storage boundary for interviewer JD and resume context."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from db import interviews
from models.schemas import (
    CreateInterviewContextRequest,
    CreateInterviewContextResponse,
    CreateInvitationRequest,
    CreateInvitationResponse,
    InterviewContextResponse,
)
from security.auth import require_bff_service, require_worker_service
from security.invitations import issue_invitation, verify_invitation
from security.rate_limit import require_capacity

router = APIRouter(prefix="/interview-contexts", tags=["interview-contexts"])


@router.post(
    "",
    response_model=CreateInterviewContextResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_interview_context(
    req: CreateInterviewContextRequest,
) -> CreateInterviewContextResponse:
    args = (req.job_description.strip(), req.resume_text.strip())
    stored = (
        await interviews.create_context(
            *args,
            req.interview_setup.model_dump(mode="python"),
            definition_id=req.definition_id,
        )
        if req.interview_setup
        else await interviews.create_context(*args, definition_id=req.definition_id)
    )
    return CreateInterviewContextResponse(**stored)


@router.get(
    "/{context_id}",
    response_model=InterviewContextResponse,
    dependencies=[Depends(require_worker_service)],
)
async def read_interview_context(context_id: str) -> InterviewContextResponse:
    stored = await interviews.get_context(context_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Interview context not found")
    return InterviewContextResponse(
        context_id=context_id,
        job_description=stored["job_description"],
        resume_text=stored["resume_text"],
        interview_setup=stored.get("interview_setup"),
        definition_id=stored.get("definition_id"),
        candidate_profile=stored.get("candidate_profile"),
    )


@router.post(
    "/{context_id}/invitations",
    response_model=CreateInvitationResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_invitation(
    context_id: str,
    req: CreateInvitationRequest,
) -> CreateInvitationResponse:
    if await interviews.get_context(context_id) is None:
        raise HTTPException(status_code=404, detail="Interview context not found")
    expires_at = interviews.utc_now() + timedelta(minutes=req.ttl_minutes)
    token = issue_invitation(
        interview_id=f"int_{context_id.removeprefix('ctx_')}",
        context_id=context_id,
        candidate_id=req.candidate_id,
        expires_at=int(expires_at.timestamp()),
    )
    payload = verify_invitation(token)
    await interviews.store_invitation(
        invitation_id=payload["jti"],
        context_id=context_id,
        candidate_id=req.candidate_id,
        expires_at=expires_at,
    )
    return CreateInvitationResponse(
        invitation_token=token,
        expires_at=expires_at,
    )
