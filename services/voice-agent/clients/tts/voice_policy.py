"""Session-pinned TTS voice policy (Milestone 5 / PBI-A3).

Pin voice at session start, preflight before admission, retry the same voice
only, then pause or end — never silently switch provider or voice_id.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from clients.errors import ServiceUnavailableError
from clients.settings import (
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_VOICE_SPEED,
    TTS_PROVIDER,
    TTS_VOICE,
)

logger = logging.getLogger("voice-agent.tts")

FallbackPolicy = Literal[
    "same_voice_retry_then_pause",
    "same_voice_retry_then_end",
    "allow_provider_fallback",
]

PREFLIGHT_PHRASE = "Voice check."
SAME_VOICE_RETRY_ATTEMPTS = 2

_ALLOWED_FALLBACK: frozenset[str] = frozenset(
    {
        "same_voice_retry_then_pause",
        "same_voice_retry_then_end",
        "allow_provider_fallback",
    }
)


@dataclass(frozen=True)
class ResolvedVoicePolicy:
    provider: str
    voice_id: str
    model_id: str
    stability: float | None
    speed: float | None
    fallback_policy: FallbackPolicy
    preflight_required: bool

    @property
    def pin_voice(self) -> bool:
        return self.fallback_policy != "allow_provider_fallback"

    @property
    def recovery_action(self) -> Literal["pause", "end"]:
        if self.fallback_policy == "same_voice_retry_then_end":
            return "end"
        return "pause"

    def log_safe(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "fallback_policy": self.fallback_policy,
            "preflight_required": self.preflight_required,
            "pin_voice": self.pin_voice,
        }


def _opt_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_voice_id(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"elevenlabs", "11labs", "eleven_labs"}:
        return (ELEVENLABS_VOICE_ID or "EXAVITQu4vr4xnSDxMaL").strip()
    return (TTS_VOICE or "alloy").strip()


def _default_model_id(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"elevenlabs", "11labs", "eleven_labs"}:
        return (ELEVENLABS_MODEL_ID or "eleven_flash_v2_5").strip()
    if normalized == "openai":
        return "tts-1"
    return ""


def resolve_voice_policy(
    raw: dict[str, Any] | None = None,
    *,
    provider_override: str | None = None,
) -> ResolvedVoicePolicy:
    """Resolve published voice_policy + env defaults into a pinned session config."""
    payload = raw if isinstance(raw, dict) else {}
    provider = (
        _opt_str(provider_override)
        or _opt_str(payload.get("provider"))
        or (TTS_PROVIDER or "self_hosted")
    )
    voice_id = _opt_str(payload.get("voice_id")) or _default_voice_id(provider)
    model_id = _opt_str(payload.get("model_id")) or _default_model_id(provider)
    fallback = _opt_str(payload.get("fallback_policy")) or "same_voice_retry_then_pause"
    if fallback not in _ALLOWED_FALLBACK:
        fallback = "same_voice_retry_then_pause"
    preflight = payload.get("preflight_required")
    if preflight is None:
        preflight_required = True
    else:
        preflight_required = bool(preflight)
    speed = _opt_float(payload.get("speed"))
    if speed is None and provider.lower() in {"elevenlabs", "11labs", "eleven_labs"}:
        speed = float(ELEVENLABS_VOICE_SPEED or 0.82)
    return ResolvedVoicePolicy(
        provider=provider,
        voice_id=voice_id,
        model_id=model_id,
        stability=_opt_float(payload.get("stability")),
        speed=speed,
        fallback_policy=fallback,  # type: ignore[arg-type]
        preflight_required=preflight_required,
    )


def voice_id_of(client: Any) -> str:
    for attr in ("voice_id", "voice"):
        value = getattr(client, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = getattr(client, "_primary", None)
    if inner is not None:
        return voice_id_of(inner)
    return ""


async def synthesize_same_voice(
    client: Any,
    text: str,
    *,
    attempts: int = SAME_VOICE_RETRY_ATTEMPTS,
) -> bytes:
    """Retry the same pinned client; never change voice_id between attempts."""
    pinned = voice_id_of(client)
    last_exc: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            audio = await client.synthesize(text)
            if audio:
                if pinned and voice_id_of(client) != pinned:
                    raise ServiceUnavailableError(
                        "tts",
                        f"voice_id changed mid-retry ({pinned} -> {voice_id_of(client)})",
                    )
                return audio
            last_exc = ServiceUnavailableError("tts", "empty audio response")
            logger.warning(
                "tts_same_voice_retry",
                extra={
                    "event": "tts_same_voice_retry",
                    "attempt": attempt,
                    "reason": "empty_audio",
                    "voice_id": pinned,
                },
            )
        except ServiceUnavailableError as exc:
            last_exc = exc
            logger.warning(
                "tts_same_voice_retry",
                extra={
                    "event": "tts_same_voice_retry",
                    "attempt": attempt,
                    "reason": type(exc).__name__,
                    "voice_id": pinned,
                },
            )
    assert last_exc is not None
    raise last_exc


async def run_tts_preflight(
    client: Any,
    policy: ResolvedVoicePolicy,
    *,
    session_id: str | None = None,
) -> None:
    """Prove the pinned voice works before admitting the candidate."""
    logger.info(
        "tts_voice_pinned",
        extra={
            "event": "tts_voice_pinned",
            "session_id": session_id,
            **policy.log_safe(),
        },
    )
    if not policy.preflight_required:
        return
    audio = await synthesize_same_voice(client, PREFLIGHT_PHRASE, attempts=2)
    if not audio:
        raise ServiceUnavailableError("tts", "preflight returned empty audio")
    if policy.voice_id and voice_id_of(client) and voice_id_of(client) != policy.voice_id:
        raise ServiceUnavailableError(
            "tts",
            f"preflight voice mismatch: expected {policy.voice_id}",
        )
    logger.info(
        "tts_preflight_ok",
        extra={
            "event": "tts_preflight_ok",
            "session_id": session_id,
            "voice_id": voice_id_of(client) or policy.voice_id,
            "audio_bytes": len(audio),
            "provider": policy.provider,
        },
    )


def log_tts_recovery(
    policy: ResolvedVoicePolicy,
    *,
    session_id: str | None,
    error: BaseException,
) -> Literal["pause", "end"]:
    action = policy.recovery_action
    logger.error(
        "tts_recovery",
        extra={
            "event": "tts_recovery",
            "session_id": session_id,
            "action": action,
            "error_type": type(error).__name__,
            "voice_id": policy.voice_id,
            "provider": policy.provider,
            "fallback_policy": policy.fallback_policy,
        },
    )
    return action
