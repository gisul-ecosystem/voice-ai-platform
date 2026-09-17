"""
Laptop 4 -- backend API
FastAPI entrypoint. Session management, Mongo, and the interview
planning endpoint. Talks to the LLM/STT/TTS nodes over HTTP -- no
models loaded locally.
"""
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from logging_config import configure_logging
from observability import set_correlation_id

load_dotenv()
configure_logging()

from routers import (  # noqa: E402
    health,
    interview_contexts,
    interviews,
    scheduled_interviews,
    session_events,
    sessions,
    tools,
)
from db.interviews import ensure_indexes  # noqa: E402
from db.mongo import close_client, get_db  # noqa: E402

logger = logging.getLogger("backend-api")


def validate_startup_configuration() -> None:
    if (os.getenv("APP_ENV") or "development").strip().lower() not in {
        "production",
        "staging",
    }:
        return
    required = {
        "MONGO_URL",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "BACKEND_SERVICE_TOKEN",
        "VOICE_AGENT_SERVICE_TOKEN",
        "INTERVIEW_INVITATION_SECRET",
    }
    if (os.getenv("LLM_PROVIDER") or "self_hosted").strip().lower() in {
        "openai",
        "openai_api",
        "api",
    }:
        required.add("OPENAI_API_KEY")
    missing = sorted(name for name in required if not (os.getenv(name) or "").strip())
    if missing:
        raise RuntimeError(
            "Missing required backend-api settings: " + ", ".join(missing)
        )


app = FastAPI(title="Voice AI Platform - Backend API")
test_frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "TEST_FRONTEND_ORIGINS",
        "http://127.0.0.1:8765,http://localhost:8765",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=test_frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(health.router)
app.include_router(interview_contexts.router)
app.include_router(interviews.router)
app.include_router(scheduled_interviews.router)
app.include_router(session_events.router)
app.include_router(sessions.router)
app.include_router(tools.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = set_correlation_id(request.headers.get("x-correlation-id"))
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-correlation-id"] = correlation_id
    logger.info(
        "http_request",
        extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "correlation_id": correlation_id,
        },
    )
    return response


@app.on_event("startup")
async def startup():
    configure_logging()
    validate_startup_configuration()
    db = get_db()
    try:
        await db.command("ping")
        await ensure_indexes()
        logger.info("startup", extra={"event": "startup", "mongo_connected": True})
    except Exception:
        logger.exception(
            "startup_failed",
            extra={"event": "startup_failed", "mongo_connected": False},
        )
        if (os.getenv("APP_ENV") or "development").strip().lower() in {
            "production",
            "staging",
        }:
            raise


@app.on_event("shutdown")
async def shutdown():
    close_client()
