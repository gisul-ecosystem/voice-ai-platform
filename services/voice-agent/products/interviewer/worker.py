"""LiveKit worker lifecycle for the Aaptor interviewer product."""
from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from clients.backend_client import fetch_interview_plan
from clients.errors import ServiceUnavailableError
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


def plan_inputs_from_job(ctx: JobContext) -> tuple[str, str]:
    metadata = parse_room_metadata(getattr(ctx.room, "metadata", None) or "")
    job_description = (
        metadata.get("job_description") or os.getenv("JOB_DESCRIPTION") or ""
    ).strip()
    resume = (metadata.get("resume_text") or os.getenv("RESUME_TEXT") or "").strip()
    return job_description, resume


async def build_outline(ctx: JobContext) -> dict:
    job_description, resume = plan_inputs_from_job(ctx)
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
    await ctx.connect()

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
    await session.start(agent=AaptorAgent(outline, clients.llm), room=ctx.room)


def run() -> None:
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "aaptor"),
            port=int(os.getenv("AAPTOR_WORKER_PORT", "8081")),
        )
    )
