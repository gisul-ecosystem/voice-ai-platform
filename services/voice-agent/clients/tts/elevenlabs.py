"""ElevenLabs text-to-speech API."""
from __future__ import annotations

import io
import logging
import time
import wave

from clients.http_util import make_timeout, request
from clients.settings import (
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_VOICE_ID,
    TTS_TIMEOUT_SECONDS,
)

logger = logging.getLogger("voice-agent.tts")


def _pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM bytes into a standard WAV container."""
    if pcm_bytes.startswith(b"RIFF"):
        return pcm_bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buf.getvalue()


class ElevenLabsTts:
    def __init__(
        self,
        *,
        base_url: str = "https://api.elevenlabs.io/v1",
        api_key: str,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.voice_id = (voice_id or ELEVENLABS_VOICE_ID or "JBFqnCBsd6RMkjVDRZzb").strip()
        self.model_id = (model_id or ELEVENLABS_MODEL_ID or "eleven_flash_v2_5").strip()

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        voice_id = (voice or self.voice_id).strip()
        started = time.perf_counter()
        resp = await request(
            "tts",
            "POST",
            f"{self.base_url}/text-to-speech/{voice_id}",
            params={"output_format": "pcm_24000"},
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            headers={"xi-api-key": self._api_key},
            json={
                "text": text,
                "model_id": self.model_id,
            },
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        raw_audio = resp.content
        audio = _pcm_to_wav(raw_audio, sample_rate=24000)
        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "tts",
                "latency_ms": latency_ms,
                "input_chars": len(text),
                "audio_bytes": len(audio),
                "provider": "elevenlabs",
            },
        )
        return audio
