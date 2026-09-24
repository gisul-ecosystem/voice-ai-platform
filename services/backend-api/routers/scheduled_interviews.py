"""Product-facing scheduling and candidate invitation lifecycle."""
from __future__ import annotations

import os
import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from brain.definition_service import publish_and_store
from brain.extractors import extract_candidate_profile
from db import candidates, definitions, interviews
from models.schemas import (
    CreateScheduledInterviewRequest,
    CreateScheduledInterviewResponse,
    InvitationPreviewRequest,
    InvitationPreviewResponse,
    RecordConsentRequest,
    ScheduledInterviewListItem,
    ScheduledInterviewListResponse,
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
    candidate_id = (req.candidate_id or "").strip() or None
    candidate_record = None
    if candidate_id:
        candidate_record = await candidates.get_candidate(candidate_id)
        if candidate_record is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if not (candidate_record.get("resume_text") or "").strip():
            raise HTTPException(status_code=422, detail="Candidate CV must be uploaded first")
        if not req.definition_id:
            raise HTTPException(
                status_code=422,
                detail="definition_id is required when scheduling an admin candidate",
            )
        if await definitions.get_definition(req.definition_id) is None:
            raise HTTPException(status_code=404, detail="Interview definition not found")

    effective_candidate_name = (
        candidate_record["name"] if candidate_record else req.candidate_name.strip()
    )
    effective_candidate_email = (
        candidate_record["email"]
        if candidate_record
        else req.candidate_email.strip().lower()
    )
    effective_resume_text = (
        candidate_record["resume_text"] if candidate_record else (req.resume_text or "").strip()
    )
    if not effective_resume_text:
        raise HTTPException(status_code=422, detail="resume_text is required")
    starts_at = req.starts_at
    if starts_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="starts_at must include a timezone")
    starts_at = starts_at.astimezone(timezone.utc)
    now = interviews.utc_now()
    if starts_at < now - timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Interview cannot start in the past")

    try:
        published = await publish_and_store(
            job_description=req.job_description.strip(),
            interview_setup=req.interview_setup,
            timezone=req.timezone,
            published_by=f"schedule:{req.source_product_id}",
            existing_definition_id=req.definition_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    expires_at = starts_at + timedelta(minutes=req.late_grace_minutes)
    interview_id = f"int_{uuid.uuid4().hex}"
    candidate_id = candidate_id or f"candidate_{uuid.uuid4().hex}"
    candidate_profile = (candidate_record or {}).get("candidate_profile")
    if not isinstance(candidate_profile, dict) or not candidate_profile:
        if isinstance(req.candidate_profile, dict) and req.candidate_profile:
            candidate_profile = req.candidate_profile
        else:
            try:
                candidate_profile = extract_candidate_profile(
                    effective_resume_text
                ).model_dump(mode="python")
            except ValueError:
                candidate_profile = None
    context = await interviews.create_context(
        req.job_description.strip(),
        effective_resume_text,
        req.interview_setup.model_dump(mode="python"),
        definition_id=published.definition_id,
        candidate_profile=candidate_profile,
        expires_at_override=starts_at
        + timedelta(
            days=max(1, int(os.getenv("INTERVIEW_CONTEXT_RETENTION_DAYS", "30")))
        ),
    )
    external_interview_id = (req.external_interview_id or "").strip() or (
        f"ext_{uuid.uuid4().hex}"
    )
    token = issue_invitation(
        interview_id=interview_id,
        context_id=context["context_id"],
        candidate_id=candidate_id,
        expires_at=int(expires_at.timestamp()),
    )
    invitation = verify_invitation(token)
    document = {
        "_id": interview_id,
        "source_product_id": req.source_product_id,
        "external_interview_id": external_interview_id,
        "candidate_id": candidate_id,
        "candidate_name": effective_candidate_name,
        "candidate_email": effective_candidate_email,
        "context_id": context["context_id"],
        "definition_id": published.definition_id,
        "invitation_id": invitation["jti"],
        "invitation_token": token,
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
        await interviews.store_invitation(
            invitation_id=invitation["jti"],
            context_id=context["context_id"],
            candidate_id=candidate_id,
            expires_at=expires_at,
        )
        await interviews.create_scheduled_interview(document)
    except interviews.ExternalInterviewConflictError as exc:
        await interviews.rollback_schedule_artifacts(
            context_id=context["context_id"],
            invitation_id=invitation["jti"],
        )
        raise HTTPException(
            status_code=409,
            detail="The external interview ID already exists for this product",
        ) from exc
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
        definition_id=published.definition_id,
    )


@router.get(
    "/interviews",
    response_model=ScheduledInterviewListResponse,
    dependencies=[Depends(require_bff_service)],
)
async def list_scheduled_interviews(
    definition_id: str,
    limit: int = 50,
) -> ScheduledInterviewListResponse:
    definition_id = (definition_id or "").strip()
    if len(definition_id) < 8:
        raise HTTPException(status_code=422, detail="definition_id is required")
    rows = await interviews.list_scheduled_interviews_by_definition(
        definition_id,
        limit=limit,
    )
    items: list[ScheduledInterviewListItem] = []
    for row in rows:
        token = row.get("invitation_token")
        token_str = token.strip() if isinstance(token, str) else None
        if token_str == "":
            token_str = None
        path = (
            f"/interview/invite/{token_str}"
            if token_str
            else None
        )
        items.append(
            ScheduledInterviewListItem(
                interview_id=str(row.get("_id") or ""),
                definition_id=row.get("definition_id"),
                candidate_name=str(row.get("candidate_name") or ""),
                candidate_email=str(row.get("candidate_email") or ""),
                status=str(row.get("status") or "scheduled"),
                starts_at=interviews.as_utc(row["starts_at"]),
                invitation_token=token_str,
                candidate_path=path,
                created_at=(
                    interviews.as_utc(row["created_at"])
                    if row.get("created_at") is not None
                    else None
                ),
            )
        )
    return ScheduledInterviewListResponse(items=items)


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
    join_not_before = interviews.as_utc(stored["join_not_before"])
    join_closes_at = interviews.as_utc(stored["join_closes_at"])
    starts_at = interviews.as_utc(stored["starts_at"])
    if status == "scheduled":
        if now < join_not_before:
            status = "upcoming"
        elif now <= join_closes_at:
            status = "ready"
        else:
            status = "expired"
    setup = stored["interview_setup"]
    return InvitationPreviewResponse(
        interview_id=stored["_id"],
        definition_id=stored.get("definition_id"),
        candidate_name=stored["candidate_name"],
        title=setup["title"],
        role=setup["role"],
        starts_at=starts_at,
        timezone=stored["timezone"],
        duration_minutes=setup["durationMinutes"],
        join_not_before=join_not_before,
        join_closes_at=join_closes_at,
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
