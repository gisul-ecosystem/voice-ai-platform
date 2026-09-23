"""TTS client factory. Env URL is the default; session can override provider+key."""
from __future__ import annotations

from typing import Any

from clients.provider_util import (
    elevenlabs_base_url,
    log_client_selected,
    normalize_provider,
    openai_base_url,
    require_key_if_needed,
    resolve_api_key,
)
from clients.settings import (
    TTS_FALLBACK_PROVIDER,
    TTS_PIN_VOICE,
    TTS_PROVIDER,
    TTS_SERVICE_URL,
)
from clients.tts.elevenlabs import ElevenLabsTts
from clients.tts.openai import OpenAITts
from clients.tts.resilient import ResilientTts
from clients.tts.self_hosted import SelfHostedTts
from clients.tts.voice_policy import ResolvedVoicePolicy, resolve_voice_policy

TtsClient = ResilientTts | SelfHostedTts | OpenAITts | ElevenLabsTts


def _build(
    provider: str,
    api_key: str,
    *,
    voice_id: str | None = None,
    model_id: str | None = None,
    stability: float | None = None,
) -> SelfHostedTts | OpenAITts | ElevenLabsTts:
    if provider == "openai":
        return OpenAITts(
            base_url=openai_base_url(),
            api_key=api_key,
            voice=voice_id,
            model=model_id or "tts-1",
        )
    if provider == "elevenlabs":
        return ElevenLabsTts(
            base_url=elevenlabs_base_url(),
            api_key=api_key,
            voice_id=voice_id,
            model_id=model_id,
            stability=stability,
        )
    return SelfHostedTts(
        base_url=TTS_SERVICE_URL,
        api_key=api_key,
        voice=voice_id,
    )


def get_tts_client(
    provider_override: str | None = None,
    api_key_override: str | None = None,
    *,
    voice_policy: ResolvedVoicePolicy | dict[str, Any] | None = None,
    voice_id: str | None = None,
) -> TtsClient:
    """Build a TTS client with session-pinned voice_id.

    Provider failover is never applied here. Use ResilientTts(..., pin_voice=False)
    only when an explicit product policy allows provider fallback.
    """
    policy = (
        voice_policy
        if isinstance(voice_policy, ResolvedVoicePolicy)
        else resolve_voice_policy(
            voice_policy if isinstance(voice_policy, dict) else None,
            provider_override=provider_override,
        )
    )
    overridden = bool((provider_override or "").strip() or (api_key_override or "").strip())
    provider = normalize_provider(
        provider_override or policy.provider,
        fallback=TTS_PROVIDER,
        service="tts",
    )
    api_key = resolve_api_key("tts", provider, api_key_override)
    require_key_if_needed("tts", provider, api_key)
    resolved_voice = (voice_id or policy.voice_id or "").strip() or None
    pin_voice = policy.pin_voice if voice_policy is not None else TTS_PIN_VOICE

    log_client_selected(
        "tts", provider, overridden=overridden, has_api_key=bool(api_key)
    )
    primary = _build(
        provider,
        api_key,
        voice_id=resolved_voice,
        model_id=policy.model_id or None,
        stability=policy.stability,
    )
    fallback = None
    if TTS_FALLBACK_PROVIDER and not pin_voice:
        try:
            fallback_provider = normalize_provider(
                TTS_FALLBACK_PROVIDER,
                fallback="self_hosted",
                service="tts",
            )
            if fallback_provider != provider:
                fallback_key = resolve_api_key("tts", fallback_provider, None)
                fallback = _build(fallback_provider, fallback_key)
        except Exception:
            fallback = None
    return ResilientTts(primary, fallback, pin_voice=pin_voice)


__all__ = [
    "ElevenLabsTts",
    "OpenAITts",
    "ResilientTts",
    "SelfHostedTts",
    "TtsClient",
    "get_tts_client",
    "resolve_voice_policy",
]
