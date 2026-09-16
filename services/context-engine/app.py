"""
CS context engine — keyword retrieval over a JSON knowledge base.

GET /retrieve?query=... returns ranked snippets. No vector DB.
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Query
from dotenv import load_dotenv

from logging_config import configure_logging
from retrieve import retrieve_context

load_dotenv()
configure_logging()

logger = logging.getLogger("context-engine")

SERVICE_PORT = int(os.getenv("SERVICE_PORT", "5555"))

app = FastAPI(title="Voice AI Platform - Context Engine")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "context-engine"}


@app.get("/retrieve")
def retrieve(query: str = Query(..., min_length=1)) -> dict:
    started = time.perf_counter()
    snippets = retrieve_context(query)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
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
    return {"query": query, "snippets": snippets}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=SERVICE_PORT)
