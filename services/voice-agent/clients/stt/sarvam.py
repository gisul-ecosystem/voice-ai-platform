"""Sarvam Saaras v3 speech-to-text: POST /speech-to-text."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import (
    SARVAM_STT_BASE_URL,
    SARVAM_STT_LANGUAGE,
    SARVAM_STT_MODE,
    SARVAM_STT_MODEL,
    STT_TIMEOUT_SECONDS,
)

logger = logging.getLogger("voice-agent.stt")


def transcript_from_payload(payload: object) -> str:
    """Sarvam returns `transcript`; keep `text` as a fallback."""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return str(payload or "")
    raw = payload.get("transcript")
    if raw is None:
        raw = payload.get("text")
    return (raw or "") if isinstance(raw, str) else str(raw or "")


class SarvamStt:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = SARVAM_STT_BASE_URL,
        model: str = SARVAM_STT_MODEL,
        mode: str = SARVAM_STT_MODE,
        language_code: str = SARVAM_STT_LANGUAGE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.mode = mode
        self.language_code = language_code

    async def transcribe(self, audio_bytes: bytes, filename: str = "chunk.wav") -> str:
        started = time.perf_counter()
        form = {
            "model": self.model,
            "mode": self.mode,
            "language_code": self.language_code,
        }
        resp = await request(
            "stt",
            "POST",
            f"{self.base_url}/speech-to-text",
            timeout=make_timeout(STT_TIMEOUT_SECONDS),
            api_key=self._api_key,
            headers={"api-subscription-key": self._api_key},
            files={"file": (filename, audio_bytes, "audio/wav")},
            data=form,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        text = transcript_from_payload(resp.json())
        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "stt",
                "latency_ms": latency_ms,
                "audio_bytes": len(audio_bytes),
                "output_chars": len(text or ""),
                "provider": "sarvam",
                "model": self.model,
                "is_final": True,
            },
        )
        return text or ""
