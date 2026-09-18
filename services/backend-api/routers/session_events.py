"""Worker-authenticated durable interview lifecycle events."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from brain import scoring_service
from db import interviews
from models.brain import ScorecardReviewRequest
from models.schemas import SessionStatusRequest, SessionTurnRequest
from security.auth import require_bff_service, require_worker_service

router = APIRouter(
    prefix="/internal/interview-sessions",
    tags=["interview-session-events"],
)
logger = logging.getLogger("backend-api.sessions")

_EXPECTED = {
    "live": ("joining", "live"),
    "completing": ("live", "completing"),
    "completed": ("live", "completing", "completed"),
    "failed": ("joining", "live", "completing"),
    "abandoned": ("joining", "live"),
}


@router.get(
    "/{session_id}",
    dependencies=[Depends(require_worker_service)],
)
async def read_session_state(session_id: str) -> dict:
    stored = await interviews.get_session(session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return {
        "session_id": session_id,
        "status": stored.get("status"),
        "definition_id": stored.get("definition_id"),
        "turns": stored.get("turns") or [],
    }


@router.get(
    "/{session_id}/transcript",
    dependencies=[Depends(require_bff_service)],
)
async def read_session_transcript(session_id: str) -> dict:
    transcript = await scoring_service.get_full_transcript(session_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return transcript


@router.get(
    "/{session_id}/scorecard",
    dependencies=[Depends(require_bff_service)],
)
async def read_session_scorecard(session_id: str) -> dict:
    from db import scorecards

    stored = await scorecards.get_scorecard(session_id)
    if stored is None:
        # Build on demand if interview already completed.
        session = await interviews.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Interview session not found")
        if session.get("status") == "completed":
            stored = await scoring_service.generate_and_store_scorecard(session_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Scorecard not found")
    payload = dict(stored)
    payload.pop("_id", None)
    reviewed = await scorecards.get_scorecard_with_review(session_id)
    return reviewed or payload


@router.post(
    "/{session_id}/scorecard/generate",
    dependencies=[Depends(require_bff_service)],
)
async def generate_session_scorecard(session_id: str) -> dict:
    session = await interviews.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    result = await scoring_service.generate_and_store_scorecard(session_id)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail="Scorecard could not be generated (missing definition or evidence)",
        )
    return result


@router.post(
    "/{session_id}/scorecard/review",
    dependencies=[Depends(require_bff_service)],
)
async def review_session_scorecard(session_id: str, req: ScorecardReviewRequest) -> dict:
    session = await interviews.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    try:
        return await scoring_service.apply_scorecard_review(session_id, req)
    except ValueError as exc:
        if str(exc) == "scorecard_not_found":
            raise HTTPException(status_code=404, detail="Scorecard not found") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{session_id}/quality-metrics",
    dependencies=[Depends(require_bff_service)],
)
async def read_session_quality_metrics(session_id: str) -> dict:
    metrics = await scoring_service.get_session_quality_metrics(session_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return metrics


@router.post(
    "/{session_id}/status",
    status_code=204,
    dependencies=[Depends(require_worker_service)],
)
async def update_session_status(
    session_id: str,
    req: SessionStatusRequest,
) -> Response:
    try:
        changed = await interviews.transition_session(
            session_id,
            expected=_EXPECTED[req.status],
            status=req.status,
            reason=req.reason,
        )
        if not changed:
            stored = await interviews.get_session(session_id)
            if stored is None:
                raise HTTPException(status_code=404, detail="Interview session not found")
            if stored.get("status") != req.status:
                raise HTTPException(status_code=409, detail="Invalid session status transition")
        if req.status == "completed":
            try:
                await scoring_service.generate_and_store_scorecard(session_id)
            except Exception:
                logger.exception(
                    "scorecard_generation_failed",
                    extra={
                        "event": "scorecard_generation_failed",
                        "session_id": session_id,
                    },
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "session_status_db_failed",
            extra={"event": "session_status_db_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail="Interview persistence is temporarily unavailable",
        ) from exc
    return Response(status_code=204)


@router.post(
    "/{session_id}/turns",
    status_code=204,
    dependencies=[Depends(require_worker_service)],
)
async def record_session_turn(
    session_id: str,
    req: SessionTurnRequest,
) -> Response:
    try:
        outcome = await interviews.append_turn(session_id, req.model_dump(mode="python"))
        if outcome == "missing":
            raise HTTPException(status_code=404, detail="Interview session not found")
        if outcome == "conflict":
            raise HTTPException(status_code=409, detail="Turn ID already has different data")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "record_turn_db_failed",
            extra={"event": "record_turn_db_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail="Interview persistence is temporarily unavailable",
        ) from exc
    return Response(status_code=204)
