"""ElevenLabs text-to-speech API."""
from __future__ import annotations

import io
import logging
import time
import wave
from collections.abc import AsyncIterator

from clients.errors import ServiceUnavailableError
from clients.http_util import make_timeout, request, stream_request
from clients.settings import (
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_VOICE_SPEED,
    TTS_TIMEOUT_SECONDS,
)

logger = logging.getLogger("voice-agent.tts")

FREE_VOICE_IDS = (
    "EXAVITQu4vr4xnSDxMaL",
    "pFZP5JQG7iQjIQuC4Bku",
    "JBFqnCBsd6RMkjVDRZzb",
)


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

    def _payload(self, text: str) -> dict:
        speed = max(0.7, min(float(ELEVENLABS_VOICE_SPEED or 0.82), 1.2))
        return {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.72,
                "similarity_boost": 0.7,
                "style": 0.0,
                "speed": speed,
                "use_speaker_boost": True,
            },
        }

    def _is_blocked(self, exc: BaseException) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in ("402", "401", "paid_plan", "payment", "unauthorized")
        )

    async def _synthesize_once(self, text: str, voice_id: str) -> bytes:
        resp = await request(
            "tts",
            "POST",
            f"{self.base_url}/text-to-speech/{voice_id}",
            params={"output_format": "pcm_24000"},
            timeout=make_timeout(TTS_TIMEOUT_SECONDS),
            headers={"xi-api-key": self._api_key},
            json=self._payload(text),
        )
        return _pcm_to_wav(resp.content, sample_rate=24000)

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        voice_id = (voice or self.voice_id).strip()
        started = time.perf_counter()
        tried = {voice_id}
        try:
            audio = await self._synthesize_once(text, voice_id)
        except ServiceUnavailableError as exc:
            if not self._is_blocked(exc):
                raise
            audio = None
            for alt in FREE_VOICE_IDS:
                if alt in tried:
                    continue
                tried.add(alt)
                try:
                    audio = await self._synthesize_once(text, alt)
                    self.voice_id = alt
                    logger.warning(
                        "tts_voice_failover",
                        extra={"event": "tts_voice_failover", "voice_id": alt},
                    )
                    break
                except ServiceUnavailableError:
                    continue
            if audio is None:
                raise
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
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

    async def stream_synthesize(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield raw PCM 24 kHz chunks as ElevenLabs produces them."""
        voice_id = (voice or self.voice_id).strip()
        started = time.perf_counter()
        first_ms: float | None = None
        audio_bytes = 0
        try:
            async with stream_request(
                "tts",
                "POST",
                f"{self.base_url}/text-to-speech/{voice_id}/stream",
                params={
                    "output_format": "pcm_24000",
                    "optimize_streaming_latency": 1,
                },
                timeout=make_timeout(TTS_TIMEOUT_SECONDS),
                headers={
                    "xi-api-key": self._api_key,
                    "accept": "application/octet-stream",
                },
                json=self._payload(text),
            ) as resp:
                async for chunk in resp.aiter_bytes(4096):
                    if not chunk:
                        continue
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - started) * 1000, 1)
                    audio_bytes += len(chunk)
                    yield chunk
        except ServiceUnavailableError:
            audio = await self.synthesize(text, voice=voice_id)
            if audio:
                audio_bytes = len(audio)
                yield audio
        logger.info(
            "stage_latency",
            extra={
                "event": "stage_latency",
                "stage": "tts",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "ttfb_ms": first_ms,
                "input_chars": len(text),
                "audio_bytes": audio_bytes,
                "provider": "elevenlabs",
                "streaming": True,
            },
        )
