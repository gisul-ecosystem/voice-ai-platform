"""STT client -- calls the Nemotron wrapper service on Laptop 2."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import STT_SERVICE_URL, STT_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.stt")


async def transcribe(audio_bytes: bytes, filename: str = "chunk.wav") -> str:
    started = time.perf_counter()
    resp = await request(
        "stt",
        "POST",
        f"{STT_SERVICE_URL}/transcribe",
        timeout=make_timeout(STT_TIMEOUT_SECONDS),
        files={"file": (filename, audio_bytes, "audio/wav")},
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    text = resp.json()["text"]
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "stt",
            "latency_ms": latency_ms,
            "audio_bytes": len(audio_bytes),
            "output_chars": len(text or ""),
        },
    )
    return text
