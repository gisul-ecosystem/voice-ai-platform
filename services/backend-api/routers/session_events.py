"""Worker-authenticated durable interview lifecycle events."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from db import interviews
from models.schemas import SessionStatusRequest, SessionTurnRequest
from security.auth import require_worker_service

router = APIRouter(
    prefix="/internal/interview-sessions",
    tags=["interview-session-events"],
    dependencies=[Depends(require_worker_service)],
)

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
    background_tasks: BackgroundTasks,
) -> Response:
    changed = await interviews.transition_session(
        session_id,
        expected=_EXPECTED[req.status],
        status=req.status,
        reason=req.reason,
    )
    if not changed and await interviews.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    if req.status == "completed":
        background_tasks.add_task(interviews.enqueue_scorecard, session_id)
    return Response(status_code=204)


@router.post("/{session_id}/turns", status_code=204)
async def record_session_turn(
    session_id: str,
    req: SessionTurnRequest,
) -> Response:
    if await interviews.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    await interviews.append_turn(session_id, req.model_dump(mode="python"))
    return Response(status_code=204)
