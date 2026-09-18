"""
Dev health aggregator for the 4-laptop setup.

GET /health/all pings STT, TTS, LLM, and the context engine so you can see
which laptops are reachable over LAN. Not a production readiness probe.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends
from dotenv import load_dotenv

from db.mongo import get_db
from security.auth import require_bff_service

load_dotenv()

logger = logging.getLogger("backend-api.health")

router = APIRouter(tags=["health"])

HEALTH_TIMEOUT_SECONDS = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "3"))


def _service_urls() -> dict[str, dict[str, str]]:
    llm_url = os.getenv("LLM_SERVICE_URL", "http://localhost:11434/v1").rstrip("/")
    stt_url = os.getenv("STT_SERVICE_URL", "http://localhost:5552").rstrip("/")
    tts_url = os.getenv("TTS_SERVICE_URL", "http://localhost:5553").rstrip("/")
    context_url = os.getenv("CONTEXT_ENGINE_URL", "http://localhost:5555").rstrip("/")
    # Ollama/vLLM both expose OpenAI-compatible GET /v1/models; STT/TTS have /health.
    llm_health = os.getenv("LLM_HEALTH_URL") or f"{llm_url}/models"
    return {
        "llm": {
            "laptop": "Laptop 1",
            "url": llm_health,
        },
        "stt": {
            "laptop": "Laptop 2",
            "url": f"{stt_url}/health",
        },
        "tts": {
            "laptop": "Laptop 3",
            "url": f"{tts_url}/health",
        },
        "context_engine": {
            "laptop": "Laptop 4",
            "url": f"{context_url}/health",
        },
    }


async def _ping(name: str, laptop: str, url: str) -> tuple[str, dict]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        detail: dict | str | None
        try:
            detail = resp.json()
        except Exception:
            detail = (resp.text or "")[:200]
        up = resp.status_code < 500
        result = {
            "laptop": laptop,
            "url": url,
            "up": up,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "detail": detail,
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        result = {
            "laptop": laptop,
            "url": url,
            "up": False,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    logger.info(
        "health_ping",
            extra={
                "event": "health_ping",
                "remote_service": name,
                "laptop": laptop,
                "up": result["up"],
                "latency_ms": result["latency_ms"],
            },
    )
    return name, result


@router.get("/health")
async def health():
    db = get_db()
    try:
        await db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
        logger.warning("mongo_ping_failed", extra={"event": "mongo_ping_failed"})
    return {"status": "ok" if mongo_ok else "degraded", "mongo_connected": mongo_ok}


@router.get(
    "/internal/bff/health",
    dependencies=[Depends(require_bff_service)],
)
async def bff_health():
    return await health()


@router.get("/health/all")
async def health_all():
    """Ping STT, TTS, and LLM /health (or /models for the LLM node)."""
    targets = _service_urls()
    ping_tasks = [
        _ping(name, spec["laptop"], spec["url"]) for name, spec in targets.items()
    ]
    pinged = await asyncio.gather(*ping_tasks)
    services = {name: body for name, body in pinged}

    db = get_db()
    try:
        await db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False

    up_flags = [body["up"] for body in services.values()]
    if all(up_flags) and mongo_ok:
        status = "ok"
    elif any(up_flags):
        status = "degraded"
    else:
        status = "down"

    payload = {
        "status": status,
        "backend": {
            "laptop": "Laptop 4",
            "up": True,
            "mongo_connected": mongo_ok,
        },
        "services": services,
    }
    logger.info(
        "health_all",
        extra={
            "event": "health_all",
            "status": status,
            "llm_up": services["llm"]["up"],
            "stt_up": services["stt"]["up"],
            "tts_up": services["tts"]["up"],
            "context_engine_up": services["context_engine"]["up"],
            "mongo_connected": mongo_ok,
        },
    )
    return payload
