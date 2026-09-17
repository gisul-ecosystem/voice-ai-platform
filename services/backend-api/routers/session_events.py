"""Worker-authenticated durable interview lifecycle events."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from db import interviews
from models.schemas import SessionStatusRequest, SessionTurnRequest
from security.auth import require_worker_service

router = APIRouter(
    prefix="/internal/interview-sessions",
    tags=["interview-session-events"],
    dependencies=[Depends(require_worker_service)],
)
logger = logging.getLogger("backend-api.sessions")

_EXPECTED = {
    "live": ("joining", "live"),
    "completing": ("live", "completing"),
    "completed": ("live", "completing", "completed"),
    "failed": ("joining", "live", "completing"),
    "abandoned": ("joining", "live"),
}


@router.get("/{session_id}")
async def read_session_state(session_id: str) -> dict:
    stored = await interviews.get_session(session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return {
        "session_id": session_id,
        "status": stored.get("status"),
        "turns": stored.get("turns") or [],
    }

@router.post("/{session_id}/status", status_code=204)
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
        if not changed and await interviews.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Interview session not found")
        if req.status == "completed":
            await interviews.enqueue_scorecard(session_id)
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


@router.post("/{session_id}/turns", status_code=204)
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

