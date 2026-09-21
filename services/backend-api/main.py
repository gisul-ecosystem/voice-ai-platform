"""
Laptop 4 -- backend API
FastAPI entrypoint. Session management, Mongo, and the interview
planning endpoint. Talks to the LLM/STT/TTS nodes over HTTP -- no
models loaded locally.
"""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from logging_config import configure_logging
from observability import set_correlation_id

load_dotenv()
configure_logging()

from routers import (  # noqa: E402
    brain_intelligence,
    brain_state,
    admin_candidates,
    health,
    interview_contexts,
    interviews,
    scheduled_interviews,
    session_events,
    sessions,
    tools,
)
from db.interviews import ensure_indexes  # noqa: E402
from db.mongo import close_client, get_db, set_fallback_mode  # noqa: E402

logger = logging.getLogger("backend-api")


_WEAK_LIVEKIT_KEYS = frozenset({"devkey", "dev", "test", "changeme"})


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
    livekit_key = (os.getenv("LIVEKIT_API_KEY") or "").strip().lower()
    allow_weak = (os.getenv("LIVEKIT_ALLOW_WEAK_API_KEY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if livekit_key in _WEAK_LIVEKIT_KEYS and not allow_weak:
        raise RuntimeError(
            "LIVEKIT_API_KEY must not be a shared/dev placeholder "
            f"({livekit_key!r}) in production/staging; set a real LiveKit API "
            "key or set LIVEKIT_ALLOW_WEAK_API_KEY=true to keep current credentials"
        )


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
        # No reachable MongoDB (e.g. local dev without a DB running) -- fall
        # back to the in-memory store so the app stays usable, just non-durable.
        set_fallback_mode(True)


async def shutdown():
    close_client()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(title="Voice AI Platform - Backend API", lifespan=lifespan)
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
app.include_router(brain_intelligence.router)
app.include_router(brain_state.router)
app.include_router(admin_candidates.router)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=5554, reload=True)

