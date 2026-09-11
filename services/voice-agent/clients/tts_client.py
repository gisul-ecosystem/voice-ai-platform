"""TTS client -- calls the Kokoro wrapper service on Laptop 3."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import TTS_SERVICE_URL, TTS_TIMEOUT_SECONDS, TTS_VOICE

logger = logging.getLogger("voice-agent.tts")


async def synthesize(text: str, voice: str | None = None) -> bytes:
    # NOTE: af_heart is American English -- Kokoro has no Indian-accented
    # English voice. See services/model-serving/tts/README.md.
    started = time.perf_counter()
    resp = await request(
        "tts",
        "POST",
        f"{TTS_SERVICE_URL}/synthesize",
        timeout=make_timeout(TTS_TIMEOUT_SECONDS),
        json={"text": text, "voice": voice or TTS_VOICE},
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    audio = resp.content
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "tts",
            "latency_ms": latency_ms,
            "input_chars": len(text),
            "audio_bytes": len(audio),
        },
    )
    return audio
