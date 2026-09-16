"""Laptop / FastAPI STT: POST /transcribe."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import STT_SERVICE_URL, STT_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.stt")


class SelfHostedStt:
    def __init__(self, *, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def transcribe(self, audio_bytes: bytes, filename: str = "chunk.wav") -> str:
        started = time.perf_counter()
        resp = await request(
            "stt",
            "POST",
            f"{self.base_url}/transcribe",
            timeout=make_timeout(STT_TIMEOUT_SECONDS),
            api_key=self._api_key or None,
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
