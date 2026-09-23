"""HTTP client for the context-engine retrieve service.

Uses the shared retry/timeout HTTP helper. Customer-support (Racko) still
depends on this endpoint; interviewer uses interview-contexts instead.
"""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import CONTEXT_ENGINE_TIMEOUT_SECONDS, CONTEXT_ENGINE_URL

logger = logging.getLogger("voice-agent.context")


async def retrieve_context(query: str) -> list[str]:
    started = time.perf_counter()
    resp = await request(
        "context-engine",
        "GET",
        f"{CONTEXT_ENGINE_URL}/retrieve",
        timeout=make_timeout(CONTEXT_ENGINE_TIMEOUT_SECONDS),
        params={"query": query},
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    snippets = list(resp.json().get("snippets") or [])
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "retrieve",
            "latency_ms": latency_ms,
            "query_chars": len(query),
            "hit_count": len(snippets),
        },
    )
    return snippets
