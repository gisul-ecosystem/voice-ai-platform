"""Deepgram text-to-speech API."""
from __future__ import annotations

import io
import logging
import re
import time
import wave
from collections.abc import AsyncGenerator

from clients.http_util import make_timeout, request, stream_request
from clients.settings import TTS_TIMEOUT_SECONDS

logger = logging.getLogger("voice-agent.clients.tts.deepgram")


def normalize_speech_text(text: str) -> str:
    """Prepare text for TTS by rewriting tricky punctuation."""
    sentences = re.split(r"(?<=[.!])\s+(?=[A-Z])", text, maxsplit=1)
    if len(sentences) != 2:
        return text
    first, rest = sentences
    if first.endswith((".", "!")) and len(first.split()) <= 6:
        first = first[:-1] + "..."
    return f"{first} {rest}"


class DeepgramTts:
    def __init__(
        self,
        *,
        base_url: str = "https://api.deepgram.com/v1",
        api_key: str,
        model: str | None = None,
        voice_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = (model or voice_id or "aura-asteria-en").strip()
        self.voice_id = self.model
        self.model_id = self.model

    async def _synthesize_once(self, text: str, model: str | None = None) -> bytes:
        active_model = (model or self.model).strip()
        resp = await request(
            "tts",
            "POST",
            f"{self.base_url}/speak",
            params={"model": active_model, "encoding": "linear16", "sample_rate": "24000"},
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            headers={"Authorization": f"Token {self._api_key}", "Content-Type": "application/json"},
            json={"text": normalize_speech_text(text)},
        )
        return resp.content

    async def synthesize(self, text: str, voice: str | None = None, **kwargs) -> bytes:
        started = time.perf_counter()
        audio = await self._synthesize_once(text, model=voice)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            f"synthesized TTS via Deepgram ({len(text)} chars)",
            extra={
                "provider": "deepgram",
                "model": voice or self.model,
                "latency_ms": latency_ms,
                "bytes": len(audio),
            },
        )
        return audio

    async def stream(self, text: str, voice: str | None = None, **kwargs) -> AsyncGenerator[bytes, None]:
        started = time.perf_counter()
        first_chunk = False
        bytes_yielded = 0
        active_model = (voice or self.model).strip()
        async with stream_request(
            "tts",
            "POST",
            f"{self.base_url}/speak",
            params={"model": active_model, "encoding": "linear16", "sample_rate": "24000"},
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            headers={"Authorization": f"Token {self._api_key}", "Content-Type": "application/json"},
            json={"text": normalize_speech_text(text)},
        ) as resp:
            async for chunk in resp.aiter_bytes(4096):
                if not chunk:
                    continue
                if not first_chunk:
                    ttfb = round((time.perf_counter() - started) * 1000, 1)
                    logger.info(
                        f"Deepgram TTFB: {ttfb}ms for {len(text)} chars",
                        extra={
                            "provider": "deepgram",
                            "model": active_model,
                            "ttfb_ms": ttfb,
                        },
                    )
                    first_chunk = True
                bytes_yielded += len(chunk)
                yield chunk

    async def stream_synthesize(self, text: str, **kwargs) -> AsyncGenerator[bytes, None]:
        voice = kwargs.get("voice") or kwargs.get("voice_id")
        async for chunk in self.stream(text, voice=voice):
            yield chunk
