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

load_dotenv()
configure_logging()

from routers import health, interviews, sessions, tools  # noqa: E402
from db.mongo import get_db  # noqa: E402

logger = logging.getLogger("backend-api")

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
app.include_router(interviews.router)
app.include_router(sessions.router)
app.include_router(tools.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "http_request",
        extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


@app.on_event("startup")
async def startup():
    configure_logging()
    db = get_db()
    try:
        await db.command("ping")
        logger.info("startup", extra={"event": "startup", "mongo_connected": True})
    except Exception:
        logger.warning("startup", extra={"event": "startup", "mongo_connected": False})
