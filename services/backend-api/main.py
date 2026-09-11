"""
Laptop 4 -- backend API
FastAPI entrypoint. Session management, Mongo, and the interview
planning endpoint. Talks to the LLM/STT/TTS nodes over HTTP -- no
models loaded locally.
"""
import logging
import time

from fastapi import FastAPI, Request
from dotenv import load_dotenv

from logging_config import configure_logging

load_dotenv()
configure_logging()

from routers import health, interviews  # noqa: E402
from db.mongo import get_db  # noqa: E402

logger = logging.getLogger("backend-api")

app = FastAPI(title="Voice AI Platform - Backend API")
app.include_router(health.router)
app.include_router(interviews.router)


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
