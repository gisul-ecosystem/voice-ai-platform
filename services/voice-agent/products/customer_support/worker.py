"""LiveKit worker lifecycle for the Racko customer-support product."""
from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from products.customer_support.agent import RackoAgent
from voice_platform.runtime import (
    attach_session_metrics,
    build_agent_session,
    load_inference_clients,
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
    session = build_agent_session(clients)
    attach_session_metrics(session, logger)
    await session.start(
        agent=RackoAgent(clients.llm, session_id=ctx.room.name),
        room=ctx.room,
    )


def run() -> None:
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("RACKO_AGENT_NAME", "racko"),
            port=int(os.getenv("RACKO_WORKER_PORT", "8082")),
        )
    )
