"""Product-facing scheduling and candidate invitation lifecycle."""
from __future__ import annotations

import os
import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from db import interviews
from models.schemas import (
    CreateScheduledInterviewRequest,
    CreateScheduledInterviewResponse,
    InvitationPreviewRequest,
    InvitationPreviewResponse,
    RecordConsentRequest,
)
from security.auth import require_bff_service
from security.invitations import issue_invitation, verify_invitation
from security.rate_limit import require_capacity

router = APIRouter(prefix="/v1", tags=["scheduled-interviews"])


@router.post(
    "/interviews",
    response_model=CreateScheduledInterviewResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_scheduled_interview(
    req: CreateScheduledInterviewRequest,
) -> CreateScheduledInterviewResponse:
    starts_at = req.starts_at
    if starts_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="starts_at must include a timezone")
    starts_at = starts_at.astimezone(timezone.utc)
    now = interviews.utc_now()
    if starts_at < now - timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Interview cannot start in the past")

    expires_at = starts_at + timedelta(minutes=req.late_grace_minutes)
    interview_id = f"int_{uuid.uuid4().hex}"
    candidate_id = f"candidate_{uuid.uuid4().hex}"
    context = await interviews.create_context(
        req.job_description.strip(),
        req.resume_text.strip(),
        req.interview_setup.model_dump(mode="python"),
        expires_at_override=starts_at
        + timedelta(
            days=max(1, int(os.getenv("INTERVIEW_CONTEXT_RETENTION_DAYS", "30")))
        ),
    )
    token = issue_invitation(
        interview_id=interview_id,
        context_id=context["context_id"],
        candidate_id=candidate_id,
        expires_at=int(expires_at.timestamp()),
    )
    invitation = verify_invitation(token)
    await interviews.store_invitation(
        invitation_id=invitation["jti"],
        context_id=context["context_id"],
        candidate_id=candidate_id,
        expires_at=expires_at,
    )
    document = {
        "_id": interview_id,
        "source_product_id": req.source_product_id,
        "external_interview_id": req.external_interview_id,
        "candidate_id": candidate_id,
        "candidate_name": req.candidate_name.strip(),
        "candidate_email": req.candidate_email.strip().lower(),
        "context_id": context["context_id"],
        "invitation_id": invitation["jti"],
        "starts_at": starts_at,
        "timezone": req.timezone,
        "join_not_before": starts_at - timedelta(minutes=req.join_early_minutes),
        "join_closes_at": expires_at,
        "status": "scheduled",
        "interview_setup": req.interview_setup.model_dump(mode="python"),
        "consent": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await interviews.create_scheduled_interview(document)
    except Exception:
        await interviews.rollback_schedule_artifacts(
            context_id=context["context_id"],
            invitation_id=invitation["jti"],
        )
        raise
    return CreateScheduledInterviewResponse(
        interview_id=interview_id,
        invitation_token=token,
        status="scheduled",
        starts_at=starts_at,
    )


async def _preview(token: str) -> tuple[dict, dict]:
    invitation = verify_invitation(token)
    stored = await interviews.get_scheduled_interview_by_invitation(
        invitation["jti"]
    )
    if stored is None or stored["_id"] != invitation["interview_id"]:
        raise HTTPException(status_code=404, detail="Interview was not found")
    return invitation, stored


@router.post(
    "/candidate/invitations/preview",
    response_model=InvitationPreviewResponse,
    dependencies=[Depends(require_capacity)],
)
async def preview_invitation(
    req: InvitationPreviewRequest,
) -> InvitationPreviewResponse:
    _, stored = await _preview(req.invitation_token)
    now = interviews.utc_now()
    status = stored["status"]
    if status == "scheduled":
        if now < stored["join_not_before"]:
            status = "upcoming"
        elif now <= stored["join_closes_at"]:
            status = "ready"
        else:
            status = "expired"
    setup = stored["interview_setup"]
    return InvitationPreviewResponse(
        interview_id=stored["_id"],
        candidate_name=stored["candidate_name"],
        title=setup["title"],
        role=setup["role"],
        starts_at=stored["starts_at"],
        timezone=stored["timezone"],
        duration_minutes=setup["durationMinutes"],
        join_not_before=stored["join_not_before"],
        join_closes_at=stored["join_closes_at"],
        monitoring_enabled=setup["monitoringEnabled"],
        recording_enabled=setup["recordingEnabled"],
        status=status,
    )


@router.post(
    "/candidate/invitations/consent",
    status_code=204,
    dependencies=[Depends(require_capacity)],
)
async def record_consent(req: RecordConsentRequest) -> Response:
    invitation, stored = await _preview(req.invitation_token)
    setup = stored["interview_setup"]
    if not req.ai_interview or not req.transcription:
        raise HTTPException(status_code=422, detail="Required consent was not granted")
    if setup["monitoringEnabled"] and not req.monitoring:
        raise HTTPException(status_code=422, detail="Monitoring consent was not granted")
    if setup["recordingEnabled"] and not req.recording:
        raise HTTPException(status_code=422, detail="Recording consent was not granted")
    changed = await interviews.record_candidate_consent(
        invitation["jti"],
        {
            "ai_interview": req.ai_interview,
            "transcription": req.transcription,
            "monitoring": req.monitoring,
            "recording": req.recording,
            "policy_version": req.policy_version,
            "recorded_at": interviews.utc_now(),
        },
    )
    if not changed:
        raise HTTPException(status_code=409, detail="Consent could not be recorded")
    return Response(status_code=204)
