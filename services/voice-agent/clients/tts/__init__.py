"""TTS client factory. Env URL is the default; session can override provider+key."""
from __future__ import annotations

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

TtsClient = ResilientTts | SelfHostedTts | OpenAITts | ElevenLabsTts


def _build(provider: str, api_key: str) -> TtsClient:
    if provider == "openai":
        return OpenAITts(base_url=openai_base_url(), api_key=api_key)
    if provider == "elevenlabs":
        return ElevenLabsTts(base_url=elevenlabs_base_url(), api_key=api_key)
    return SelfHostedTts(base_url=TTS_SERVICE_URL, api_key=api_key)


def get_tts_client(
    provider_override: str | None = None,
    api_key_override: str | None = None,
) -> TtsClient:
    overridden = bool((provider_override or "").strip() or (api_key_override or "").strip())
    provider = normalize_provider(
        provider_override,
        fallback=TTS_PROVIDER,
        service="tts",
    )
    api_key = resolve_api_key("tts", provider, api_key_override)
    require_key_if_needed("tts", provider, api_key)

    log_client_selected(
        "tts", provider, overridden=overridden, has_api_key=bool(api_key)
    )
    primary = _build(provider, api_key)
    fallback = None
    if TTS_FALLBACK_PROVIDER:
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
    return ResilientTts(primary, fallback, pin_voice=TTS_PIN_VOICE)
