"""Sarvam Saaras v3 speech-to-text: REST plus realtime WebSocket helpers."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

from clients.http_util import make_timeout, request
from clients.settings import (
    SARVAM_STT_BASE_URL,
    SARVAM_STT_LANGUAGE,
    SARVAM_STT_MODE,
    SARVAM_STT_MODEL,
    SARVAM_STT_STREAM_TYPE,
    STT_TIMEOUT_SECONDS,
)

logger = logging.getLogger("voice-agent.stt")

# Auto-detect needs ~3s of audio. Short VAD clips often come back empty.
_SHORT_CLIP_FALLBACKS = ("en-IN", "hi-IN")


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


def realtime_language_code(language_code: str) -> str:
    if language_code in {"unknown", "", "auto"}:
        return "auto"
    return language_code


def realtime_model(model: str) -> str:
    name = (model or "").strip() or "saaras:v3"
    if name.endswith("-realtime"):
        return name
    if name.startswith("saaras:v4"):
        return "saaras:v4"
    return "saaras:v3-realtime"


def http_to_ws_base(base_url: str) -> str:
    http = (base_url or "").rstrip("/")
    if http.startswith("https://"):
        return "wss://" + http[len("https://") :]
    if http.startswith("http://"):
        return "ws://" + http[len("http://") :]
    if http.startswith(("wss://", "ws://")):
        return http
    return f"wss://{http}" if http else "wss://api.sarvam.ai"


def build_realtime_ws_url(
    base_url: str,
    *,
    language_code: str,
    model: str,
    mode: str,
    stream_type: str = "fast",
    sample_rate: int = 16000,
) -> str:
    ws = http_to_ws_base(base_url)
    if not ws.endswith("/speech-to-text-realtime/ws"):
        ws = f"{ws}/speech-to-text-realtime/ws"
    query = urlencode(
        {
            "language_code": realtime_language_code(language_code),
            "model": realtime_model(model),
            "stream_type": stream_type or "fast",
            "mode": mode or "transcribe",
            "endpointing": "vad",
            "encoding": "linear16",
            "sample_rate": str(sample_rate),
            # Sarvam's own server-side endpointing — independent of the LiveKit VAD.
            # Kept short for responsiveness; the LiveKit-side grace-period commit
            # (see livekit_adapters.py) absorbs late corrections without this delay.
            "silence_duration_ms": "700",
            "min_speech_duration_ms": "250",
        }
    )
    return f"{ws}?{query}"


def parse_realtime_message(payload: object) -> tuple[str, str]:
    """Classify a Sarvam realtime JSON event as partial|final|speech_start|speech_end|other."""
    if not isinstance(payload, dict):
        return "other", ""
    event = str(payload.get("event") or payload.get("type") or "")
    text = payload.get("text")
    if not isinstance(text, str):
        text = payload.get("transcript")
    if not isinstance(text, str):
        nested = payload.get("data")
        if isinstance(nested, dict) and isinstance(nested.get("text"), str):
            text = nested["text"]
        elif isinstance(nested, dict):
            text = transcript_from_payload(nested)
        elif isinstance(nested, list):
            parts = [
                transcript_from_payload(item)
                for item in nested
                if isinstance(item, (dict, str))
            ]
            text = " ".join(part.strip() for part in parts if part.strip())
        else:
            text = transcript_from_payload(payload)
    text = (text or "").strip()
    if event in {"transcript.partial", "partial_transcript", "interim_transcript"}:
        return "partial", text
    if event in {"transcript.final", "final_transcript"}:
        return "final", text
    if event in {"vad.speech_start", "speech_start", "start_of_speech"}:
        return "speech_start", text
    if event in {"vad.speech_end", "speech_end", "end_of_speech"}:
        return "speech_end", text
    return "other", text


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
        self.stream_type = SARVAM_STT_STREAM_TYPE

    def realtime_ws_url(self, sample_rate: int = 16000) -> str:
        return build_realtime_ws_url(
            self.base_url,
            language_code=self.language_code,
            model=self.model,
            mode=self.mode,
            stream_type=self.stream_type,
            sample_rate=sample_rate,
        )

    @property
    def subscription_key(self) -> str:
        return self._api_key

    async def _post(
        self, audio_bytes: bytes, filename: str, language_code: str
    ) -> str:
        resp = await request(
            "stt",
            "POST",
            f"{self.base_url}/speech-to-text",
            timeout=make_timeout(STT_TIMEOUT_SECONDS),
            headers={"api-subscription-key": self._api_key},
            files={"file": (filename, audio_bytes, "audio/wav")},
            data={
                "model": self.model,
                "mode": self.mode,
                "language_code": language_code,
            },
        )
        return transcript_from_payload(resp.json())

    async def transcribe(self, audio_bytes: bytes, filename: str = "chunk.wav") -> str:
        started = time.perf_counter()
        languages = [self.language_code]
        if self.language_code in {"unknown", ""}:
            languages.extend(
                lang for lang in _SHORT_CLIP_FALLBACKS if lang not in languages
            )
        text = ""
        used_language = self.language_code
        for language_code in languages:
            text = await self._post(audio_bytes, filename, language_code)
            used_language = language_code
            if text.strip():
                break
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
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
                "language_code": used_language,
                "is_final": True,
            },
        )
        return text or ""
