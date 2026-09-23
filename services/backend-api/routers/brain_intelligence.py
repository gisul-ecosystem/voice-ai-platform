"""Creator-facing JD/resume intelligence extract and ingest APIs (Milestone 1+2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from brain.compiler import compile_blueprint
from brain.documents import DocumentIngestError, extract_document_text
from brain.llm_extract import (
    extract_candidate_profile_async,
    extract_job_intelligence_async,
    recommend_competencies_async,
)
from brain.publish import publish_definition, validate_for_publication
from db import definitions
from models.brain import (
    CandidateProfile,
    DurationMinutes,
    InterviewDefinitionDraft,
    InterviewDefinitionVersion,
    JobIntelligence,
    PublicationValidationResult,
    SeniorityLevel,
    utc_now,
)
from security.auth import require_bff_service, require_worker_service
from security.rate_limit import require_capacity

router = APIRouter(
    prefix="/interview-brain",
    tags=["interview-brain-intelligence"],
)

_ALLOWED_KINDS = {"jd", "resume"}


class ExtractJobRequest(BaseModel):
    job_description: str = Field(min_length=1, max_length=100_000)
    target_level: SeniorityLevel | None = None
    domain: str | None = Field(default=None, max_length=120)


class ExtractResumeRequest(BaseModel):
    resume_text: str = Field(min_length=1, max_length=100_000)


class ApproveJobRequest(BaseModel):
    job_intelligence: JobIntelligence
    approved_by: str = Field(min_length=1, max_length=128)


class ConfirmResumeRequest(BaseModel):
    candidate_profile: CandidateProfile
    confirmed_by: str = Field(min_length=1, max_length=128)


class DocumentIngestResponse(BaseModel):
    kind: str
    filename: str
    content_type: str
    page_count: int | None = None
    text: str
    warnings: list[str] = Field(default_factory=list)
    job_intelligence: JobIntelligence | None = None
    candidate_profile: CandidateProfile | None = None


class CompileBlueprintRequest(BaseModel):
    job_intelligence: JobIntelligence
    title: str | None = Field(default=None, max_length=160)
    language: str = Field(default="English", min_length=2, max_length=32)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    duration_minutes: DurationMinutes = 30
    creator_competencies: list[str] = Field(default_factory=list, max_length=8)
    resume_required: bool = False
    include_scenarios: bool = True


class PublishBlueprintRequest(BaseModel):
    draft: InterviewDefinitionDraft
    published_by: str = Field(min_length=1, max_length=128)
    template_id: str | None = Field(default=None, max_length=64)
    version: int = Field(default=1, ge=1)
    definition_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[1-9][0-9]*$",
    )


@router.post(
    "/jd/extract",
    response_model=JobIntelligence,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def extract_jd(req: ExtractJobRequest) -> JobIntelligence:
    try:
        return await extract_job_intelligence_async(
            req.job_description,
            target_level=req.target_level,
            domain=req.domain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/resume/extract",
    response_model=CandidateProfile,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def extract_resume(req: ExtractResumeRequest) -> CandidateProfile:
    try:
        return await extract_candidate_profile_async(req.resume_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/documents/ingest",
    response_model=DocumentIngestResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def ingest_document(
    kind: str = Form(...),
    file: UploadFile = File(...),
    target_level: str | None = Form(default=None),
    domain: str | None = Form(default=None),
) -> DocumentIngestResponse:
    normalized_kind = (kind or "").strip().lower()
    if normalized_kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=422, detail="kind must be jd or resume")
    raw = await file.read()
    try:
        extracted = extract_document_text(
            data=raw,
            filename=file.filename or "upload",
            content_type=file.content_type,
        )
    except DocumentIngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_intelligence: JobIntelligence | None = None
    candidate_profile: CandidateProfile | None = None
    try:
        if normalized_kind == "jd":
            level: SeniorityLevel | None = None
            if target_level in {"intern", "junior", "mid", "senior", "lead"}:
                level = target_level  # type: ignore[assignment]
            job_intelligence = await extract_job_intelligence_async(
                extracted.text,
                target_level=level,
                domain=domain,
            )
        else:
            candidate_profile = await extract_candidate_profile_async(extracted.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return DocumentIngestResponse(
        kind=normalized_kind,
        filename=extracted.filename,
        content_type=extracted.content_type,
        page_count=extracted.page_count,
        text=extracted.text,
        warnings=extracted.warnings,
        job_intelligence=job_intelligence,
        candidate_profile=candidate_profile,
    )


@router.post(
    "/jd/approve",
    response_model=JobIntelligence,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def approve_jd(req: ApproveJobRequest) -> JobIntelligence:
    payload = req.job_intelligence.model_copy(
        update={"approved": True, "approved_at": utc_now()}
    )
    if not payload.role.title.strip():
        raise HTTPException(status_code=422, detail="role title is required")
    if not payload.raw_job_description.strip():
        raise HTTPException(status_code=422, detail="raw_job_description is required")
    return payload


@router.post(
    "/resume/confirm",
    response_model=CandidateProfile,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def confirm_resume(req: ConfirmResumeRequest) -> CandidateProfile:
    claims = [
        claim.model_copy(
            update={
                "provenance": claim.provenance.model_copy(
                    update={"confirmed": True}
                )
            }
        )
        for claim in req.candidate_profile.claims
    ]
    return req.candidate_profile.model_copy(
        update={
            "confirmed": True,
            "confirmed_at": utc_now(),
            "claims": claims,
        }
    )


@router.post(
    "/blueprint/compile",
    response_model=InterviewDefinitionDraft,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def compile_interview_blueprint(
    req: CompileBlueprintRequest,
) -> InterviewDefinitionDraft:
    try:
        recommended = await recommend_competencies_async(
            req.job_intelligence,
            title=req.title,
            duration_minutes=int(req.duration_minutes),
            creator_guidance=list(req.creator_competencies or []),
        )
        return compile_blueprint(
            job_intelligence=req.job_intelligence,
            title=req.title,
            language=req.language,
            timezone=req.timezone,
            duration_minutes=req.duration_minutes,
            creator_competencies=list(req.creator_competencies or []),
            recommended_competencies=recommended or None,
            creator_exclusive=bool(recommended),
            resume_required=req.resume_required,
            include_scenarios=req.include_scenarios,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/blueprint/validate",
    response_model=PublicationValidationResult,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def validate_interview_blueprint(
    draft: InterviewDefinitionDraft,
) -> PublicationValidationResult:
    return validate_for_publication(draft)


@router.post(
    "/blueprint/publish",
    response_model=InterviewDefinitionVersion,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def publish_interview_blueprint(
    req: PublishBlueprintRequest,
) -> InterviewDefinitionVersion:
    try:
        published = publish_definition(
            req.draft,
            template_id=req.template_id,
            version=req.version,
            published_by=req.published_by,
            definition_id=req.definition_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    outcome = await definitions.save_definition(published)
    if outcome == "duplicate":
        raise HTTPException(
            status_code=409,
            detail="definition_id is already published; use a new versioned definition_id",
        )
    return published


@router.get(
    "/definitions/{definition_id}",
    response_model=InterviewDefinitionVersion,
    dependencies=[Depends(require_worker_service)],
)
async def get_interview_definition(definition_id: str) -> InterviewDefinitionVersion:
    stored = await definitions.get_definition_model(definition_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Interview definition not found")
    return stored
