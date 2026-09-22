"""Laptop / FastAPI TTS: POST /synthesize."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import TTS_TIMEOUT_SECONDS, TTS_VOICE

logger = logging.getLogger("voice-agent.tts")


class SelfHostedTts:
    def __init__(self, *, base_url: str, api_key: str = "", voice: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        # Session-pinned voice — synthesize() ignores per-call overrides.
        self.voice = voice or TTS_VOICE
        self.voice_id = self.voice

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        started = time.perf_counter()
        voice_id = self.voice
        resp = await request(
            "tts",
            "POST",
            f"{self.base_url}/synthesize",
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            api_key=self._api_key or None,
            json={"text": text, "voice": voice_id},
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
                "provider": "self_hosted",
                "voice_id": voice_id,
            },
        )
        return audio
