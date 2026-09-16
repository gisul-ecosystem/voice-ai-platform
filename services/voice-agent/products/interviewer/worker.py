"""LiveKit worker lifecycle for the Aaptor interviewer product."""
from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from clients.backend_client import (
    fetch_interview_context,
    fetch_interview_plan,
    fetch_session_state,
    record_session_turn,
    report_session_status,
)
from clients.errors import ServiceUnavailableError
from clients.http_util import close_http_client
from clients.inference import parse_room_metadata
from products.interviewer.agent import AaptorAgent
from voice_platform.runtime import (
    attach_session_metrics,
    build_agent_session,
    load_inference_clients,
)

logger = logging.getLogger("voice-agent.aaptor")

GENERIC_OUTLINE = {
    "phases": [
        {
            "name": "warm-up",
            "duration_minutes": 5,
            "topics": ["background", "motivation"],
            "source": "generic",
        },
        {
            "name": "core skills",
            "duration_minutes": 10,
            "topics": ["recent work", "problem solving"],
            "source": "generic",
        },
    ]
}

VoicePipelineAgent = AgentSession


def context_id_from_job(ctx: JobContext) -> str | None:
    metadata = job_metadata(ctx)
    value = metadata.get("context_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def job_metadata(ctx: JobContext) -> dict:
    job = getattr(ctx, "job", None)
    raw = getattr(job, "metadata", None) or getattr(ctx.room, "metadata", None) or ""
    return parse_room_metadata(raw)


async def plan_inputs_from_job(ctx: JobContext) -> tuple[str, str]:
    context_id = context_id_from_job(ctx)
    if context_id:
        context = await fetch_interview_context(context_id)
        return (
            str(context.get("job_description") or "").strip(),
            str(context.get("resume_text") or "").strip(),
        )
    if (os.getenv("APP_ENV") or "development").lower() not in {
        "production",
        "staging",
    }:
        return (
            (os.getenv("JOB_DESCRIPTION") or "").strip(),
            (os.getenv("RESUME_TEXT") or "").strip(),
        )
    return "", ""


async def build_outline(ctx: JobContext) -> dict:
    try:
        job_description, resume = await plan_inputs_from_job(ctx)
    except ServiceUnavailableError:
        logger.exception(
            "interview_context_fetch_failed",
            extra={"event": "interview_context_fetch_failed"},
        )
        return GENERIC_OUTLINE
    if not job_description or not resume:
        logger.warning(
            "plan_inputs_missing",
            extra={
                "event": "plan_inputs_missing",
                "has_jd": bool(job_description),
                "has_resume": bool(resume),
            },
        )
        return GENERIC_OUTLINE
    try:
        return await fetch_interview_plan(job_description, resume)
    except ServiceUnavailableError:
        logger.exception("stage1_plan_failed", extra={"event": "stage1_plan_failed"})
        return GENERIC_OUTLINE


async def entrypoint(ctx: JobContext) -> None:
    if hasattr(ctx, "log_context_fields"):
        ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("session_start", extra={"event": "session_start", "room": ctx.room.name})
    if hasattr(ctx, "add_shutdown_callback"):
        ctx.add_shutdown_callback(close_http_client)
    await ctx.connect()

    metadata = job_metadata(ctx)
    session_id = str(metadata.get("session_id") or "").strip()
    if session_id:
        try:
            await report_session_status(session_id, "live")
        except ServiceUnavailableError:
            logger.exception(
                "session_live_status_failed",
                extra={"event": "session_live_status_failed"},
            )

    clients = load_inference_clients(ctx, logger)
    outline = await build_outline(ctx)
    logger.info(
        "stage1_outline",
        extra={
            "event": "stage1_outline",
            "phase_count": len(outline.get("phases") or []),
            "phases": [phase.get("name") for phase in (outline.get("phases") or [])],
        },
    )

    session = build_agent_session(clients)
    attach_session_metrics(session, logger)
    initial_state: dict = {}
    if session_id:
        try:
            stored = await fetch_session_state(session_id)
            turns = stored.get("turns") if isinstance(stored, dict) else []
            if isinstance(turns, list) and turns:
                phase_index = max(
                    (
                        int(turn.get("phase_index", 0))
                        for turn in turns
                        if isinstance(turn, dict)
                    ),
                    default=0,
                )
                candidate_turns = [
                    str(turn.get("text") or "")
                    for turn in turns
                    if isinstance(turn, dict)
                    and turn.get("speaker") == "candidate"
                    and turn.get("text")
                ]
                probe_count = sum(
                    1
                    for turn in turns
                    if isinstance(turn, dict)
                    and turn.get("speaker") == "candidate"
                    and int(turn.get("phase_index", 0)) == phase_index
                )
                initial_state = {
                    "initial_phase_index": phase_index,
                    "initial_probe_count": probe_count,
                    "candidate_turns": candidate_turns,
                }
        except ServiceUnavailableError:
            logger.exception(
                "session_restore_failed",
                extra={"event": "session_restore_failed"},
            )

    async def turn_sink(**turn) -> None:
        if session_id:
            await record_session_turn(session_id, **turn)

    async def status_sink(status: str, *, reason: str | None = None) -> None:
        if session_id:
            await report_session_status(session_id, status, reason=reason)

    await session.start(
        agent=AaptorAgent(
            outline,
            clients.llm,
            initial_state=initial_state,
            turn_sink=turn_sink,
            status_sink=status_sink,
        ),
        room=ctx.room,
    )


def run() -> None:
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "aaptor"),
            port=int(os.getenv("AAPTOR_WORKER_PORT", "8081")),
        )
    )
