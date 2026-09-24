"""Worker-authenticated interview brain state APIs (3-layer store)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from brain import state_store
from models.brain import (
    InterviewAnswerRecord,
    InterviewBrainState,
    InterviewEvidenceRecord,
    InterviewQuestionRecord,
)
from security.auth import require_worker_service

router = APIRouter(
    prefix="/internal/interview-sessions",
    tags=["interview-brain-state"],
    dependencies=[Depends(require_worker_service)],
)
logger = logging.getLogger("backend-api.brain")


@router.get("/{session_id}/brain")
async def get_brain_state(session_id: str) -> dict:
    try:
        bundle = await state_store.session_memory_bundle(session_id)
    except Exception as exc:
        logger.exception(
            "brain_read_failed",
            extra={"event": "brain_read_failed", "session_id": session_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Interview brain state is temporarily unavailable",
        ) from exc
    if (bundle["state"] is None and not bundle["questions"]):
        # First join — empty memory is normal; agent creates state after opening.
        return {
            "state": None,
            "questions": [],
            "answers": [],
            "evidence": [],
        }
    return bundle


@router.put("/{session_id}/brain")
async def put_brain_state(session_id: str, state: InterviewBrainState) -> dict:
    if state.session_id != session_id:
        raise HTTPException(
            status_code=422,
            detail="session_id in body must match path",
        )
    try:
        result = await state_store.save_brain_state(state)
    except Exception as exc:
        logger.exception(
            "brain_write_failed",
            extra={"event": "brain_write_failed", "session_id": session_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Interview brain state is temporarily unavailable",
        ) from exc
    if not result["ok"]:
        raise HTTPException(
            status_code=409,
            detail="Brain state version conflict",
        )
    return result


@router.post("/{session_id}/brain/questions", status_code=204)
async def post_brain_question(
    session_id: str,
    record: InterviewQuestionRecord,
) -> Response:
    if record.session_id != session_id:
        raise HTTPException(status_code=422, detail="session_id mismatch")
    outcome = await state_store.record_question(record)
    if outcome == "conflict":
        raise HTTPException(status_code=409, detail="Question already has different data")
    return Response(status_code=204)


@router.post("/{session_id}/brain/answers", status_code=204)
async def post_brain_answer(
    session_id: str,
    record: InterviewAnswerRecord,
) -> Response:
    if record.session_id != session_id:
        raise HTTPException(status_code=422, detail="session_id mismatch")
    outcome = await state_store.record_answer(record)
    if outcome == "conflict":
        raise HTTPException(status_code=409, detail="Answer already has different data")
    return Response(status_code=204)


@router.post("/{session_id}/brain/evidence", status_code=204)
async def post_brain_evidence(
    session_id: str,
    record: InterviewEvidenceRecord,
) -> Response:
    if record.session_id != session_id:
        raise HTTPException(status_code=422, detail="session_id mismatch")
    outcome = await state_store.record_evidence(record)
    if outcome == "conflict":
        raise HTTPException(status_code=409, detail="Evidence already has different data")
    return Response(status_code=204)
