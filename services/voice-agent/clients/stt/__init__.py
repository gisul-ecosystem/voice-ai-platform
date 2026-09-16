"""STT client factory. Env URL is the default; session can override provider+key."""
from __future__ import annotations

from clients.provider_util import (
    log_client_selected,
    normalize_provider,
    openai_base_url,
    require_key_if_needed,
    resolve_api_key,
)
from clients.settings import STT_PROVIDER, STT_SERVICE_URL
from clients.stt.openai import OpenAIStt
from clients.stt.self_hosted import SelfHostedStt

SttClient = SelfHostedStt | OpenAIStt

_DEFAULT: SttClient | None = None


def _build(provider: str, api_key: str) -> SttClient:
    if provider == "openai":
        return OpenAIStt(base_url=openai_base_url(), api_key=api_key)
    return SelfHostedStt(base_url=STT_SERVICE_URL, api_key=api_key)


def get_stt_client(
    provider_override: str | None = None,
    api_key_override: str | None = None,
) -> SttClient:
    overridden = bool((provider_override or "").strip() or (api_key_override or "").strip())
    provider = normalize_provider(provider_override, fallback=STT_PROVIDER)
    api_key = resolve_api_key("stt", provider, api_key_override)
    require_key_if_needed("stt", provider, api_key)

    if not overridden:
        global _DEFAULT
        if _DEFAULT is None:
            log_client_selected(
                "stt", provider, overridden=False, has_api_key=bool(api_key)
            )
            _DEFAULT = _build(provider, api_key)
        return _DEFAULT
    log_client_selected("stt", provider, overridden=True, has_api_key=bool(api_key))
    return _build(provider, api_key)
