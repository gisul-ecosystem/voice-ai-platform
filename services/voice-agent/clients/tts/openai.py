"""OpenAI audio/speech API. Request WAV so LiveKit adapters stay unchanged."""
from __future__ import annotations

import logging
import time

from clients.http_util import make_timeout, request
from clients.settings import TTS_TIMEOUT_SECONDS, TTS_VOICE

logger = logging.getLogger("voice-agent.tts")

_OPENAI_VOICES = frozenset(
    {"alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "verse", "ballad", "ash", "sage"}
)


def _voice(requested: str | None) -> str:
    name = (requested or TTS_VOICE or "alloy").strip().lower()
    if name in _OPENAI_VOICES:
        return name
    return "alloy"


class OpenAITts:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "tts-1",
        voice: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        # Session-pinned voice — synthesize() ignores per-call overrides.
        self.voice_id = _voice(voice)
        self.voice = self.voice_id

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        started = time.perf_counter()
        voice_id = self.voice_id
        resp = await request(
            "tts",
            "POST",
            f"{self.base_url}/audio/speech",
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            api_key=self._api_key,
            json={
                "model": self.model,
                "input": text,
                "voice": voice_id,
                "response_format": "wav",
            },
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
                "provider": "openai",
                "voice_id": voice_id,
            },
        )
        return audio
