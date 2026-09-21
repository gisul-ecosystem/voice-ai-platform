"""Admin candidate creation and CV upload endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from brain.documents import DocumentIngestError, extract_document_text
from brain.llm_extract import extract_candidate_profile_async
from db import candidates
from security.auth import require_bff_service
from security.rate_limit import require_capacity

router = APIRouter(prefix="/admin/candidates", tags=["admin-candidates"])


class CreateCandidateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    created_by: str = Field(min_length=1, max_length=128)


class CandidateResponse(BaseModel):
    candidate_id: str
    name: str
    email: str
    resume_uploaded: bool
    resume_filename: str | None = None


@router.post(
    "",
    response_model=CandidateResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_admin_candidate(req: CreateCandidateRequest) -> CandidateResponse:
    candidate_id = f"candidate_{uuid.uuid4().hex}"
    document = await candidates.create_candidate(
        candidate_id=candidate_id,
        name=req.name,
        email=req.email,
        created_by=req.created_by,
    )
    return CandidateResponse(
        candidate_id=document["candidate_id"],
        name=document["name"],
        email=document["email"],
        resume_uploaded=False,
    )


@router.post(
    "/{candidate_id}/resume",
    response_model=CandidateResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def upload_candidate_resume(
    candidate_id: str,
    file: UploadFile = File(...),
) -> CandidateResponse:
    candidate = await candidates.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    raw = await file.read()
    try:
        extracted = extract_document_text(
            data=raw,
            filename=file.filename or "resume",
            content_type=file.content_type,
        )
        profile = await extract_candidate_profile_async(extracted.text)
    except (DocumentIngestError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await candidates.attach_resume(
        candidate_id,
        resume_text=extracted.text,
        candidate_profile=profile.model_dump(mode="python"),
        filename=extracted.filename,
        content_type=extracted.content_type,
    )
    return CandidateResponse(
        candidate_id=candidate["candidate_id"],
        name=candidate["name"],
        email=candidate["email"],
        resume_uploaded=True,
        resume_filename=extracted.filename,
    )
