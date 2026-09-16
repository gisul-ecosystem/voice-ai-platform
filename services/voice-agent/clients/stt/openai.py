"""OpenAI Whisper transcriptions API."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import STT_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.stt")


class OpenAIStt:
    def __init__(self, *, base_url: str, api_key: str, model: str = "whisper-1") -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model

    async def transcribe(self, audio_bytes: bytes, filename: str = "chunk.wav") -> str:
        started = time.perf_counter()
        resp = await request(
            "stt",
            "POST",
            f"{self.base_url}/audio/transcriptions",
            timeout=make_timeout(STT_TIMEOUT_SECONDS),
            api_key=self._api_key,
            files={"file": (filename, audio_bytes, "audio/wav")},
            data={"model": self.model},
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        payload = resp.json()
        text = payload.get("text") if isinstance(payload, dict) else str(payload)
        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "stt",
                "latency_ms": latency_ms,
                "audio_bytes": len(audio_bytes),
                "output_chars": len(text or ""),
                "provider": "openai",
            },
        )
        return text or ""
