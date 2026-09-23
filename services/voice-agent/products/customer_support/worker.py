"""LiveKit worker lifecycle for the Racko customer-support product."""
from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession, JobContext, JobProcess, WorkerOptions, cli

from products.customer_support.agent import RackoAgent
from voice_platform.runtime import (
    attach_session_metrics,
    build_agent_session,
    load_inference_clients,
    prewarm_runtime,
)

logger = logging.getLogger("voice-agent.racko")

VoicePipelineAgent = AgentSession


async def entrypoint(ctx: JobContext) -> None:
    if hasattr(ctx, "log_context_fields"):
        ctx.log_context_fields = {"room": ctx.room.name}
    logger.info(
        "session_start",
        extra={
            "event": "session_start",
            "session_id": ctx.room.name,
            "room": ctx.room.name,
        },
    )
    await ctx.connect()

    clients = load_inference_clients(ctx, logger)
    vad = None
    proc = getattr(ctx, "proc", None)
    userdata = getattr(proc, "userdata", None) if proc is not None else None
    if isinstance(userdata, dict):
        vad = userdata.get("vad")
    session = build_agent_session(clients, vad=vad)
    attach_session_metrics(session, logger)
    await session.start(
        agent=RackoAgent(clients.llm, session_id=ctx.room.name),
        room=ctx.room,
    )


def prewarm(proc: JobProcess) -> None:
    prewarm_runtime(proc)


def run() -> None:
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=os.getenv("RACKO_AGENT_NAME", "racko"),
            port=int(os.getenv("RACKO_WORKER_PORT", "8082")),
        )
    )
