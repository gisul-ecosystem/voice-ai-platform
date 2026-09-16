"""Resolve provider name + API key for a session. Never log keys."""
from __future__ import annotations

import logging

from clients.errors import ProviderConfigError
from clients.settings import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_BASE_URL,
    LLM_API_KEY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    SARVAM_API_KEY,
    STT_API_KEY,
    TTS_API_KEY,
)

logger = logging.getLogger("voice-agent.providers")

SELF_HOSTED_ALIASES = frozenset(
    {"self_hosted", "self-hosted", "ollama", "vllm", "laptop", "nemotron", "kokoro"}
)
OPENAI_ALIASES = frozenset({"openai", "openai_api", "api"})
ELEVENLABS_ALIASES = frozenset({"elevenlabs", "eleven_labs", "eleven-labs", "11labs"})
SARVAM_ALIASES = frozenset({"sarvam", "sarvaam", "saaras", "s3", "saaras_v3", "saaras:v3"})
KEYED_PROVIDERS = frozenset({"openai", "sarvam", "elevenlabs"})
SUPPORTED_BY_SERVICE = {
    "llm": frozenset({"self_hosted", "openai"}),
    "stt": frozenset({"self_hosted", "openai", "sarvam"}),
    "tts": frozenset({"self_hosted", "openai", "elevenlabs"}),
}

_ENV_KEY = {"llm": LLM_API_KEY, "stt": STT_API_KEY, "tts": TTS_API_KEY}


def normalize_provider(
    raw: str | None,
    *,
    fallback: str,
    service: str | None = None,
) -> str:
    name = (raw or "").strip().lower().replace(" ", "_")
    if not name:
        name = (fallback or "self_hosted").strip().lower().replace(" ", "_")

    provider: str | None = None
    if name in SELF_HOSTED_ALIASES:
        provider = "self_hosted"
    elif name in OPENAI_ALIASES:
        provider = "openai"
    elif name in SARVAM_ALIASES:
        provider = "sarvam"
    elif name in ELEVENLABS_ALIASES:
        provider = "elevenlabs"

    if provider is None:
        raise ProviderConfigError(
            service or "inference",
            name,
            f"Unknown provider {name!r}. Use self_hosted, openai, sarvam, "
            "or elevenlabs.",
        )

    if service is not None:
        allowed = SUPPORTED_BY_SERVICE.get(service)
        if allowed is None:
            raise ProviderConfigError(
                service,
                provider,
                f"Unknown inference service {service!r}.",
            )
        if provider not in allowed:
            choices = ", ".join(sorted(allowed))
            raise ProviderConfigError(
                service,
                provider,
                f"{service.upper()} does not support provider {provider!r}. "
                f"Use one of: {choices}.",
            )

    return provider


def resolve_api_key(service: str, provider: str, api_key_override: str | None) -> str:
    if api_key_override and api_key_override.strip():
        return api_key_override.strip()
    specific = (_ENV_KEY.get(service) or "").strip()
    if specific:
        return specific
    if provider == "sarvam" and service == "stt" and SARVAM_API_KEY:
        return SARVAM_API_KEY
    if provider == "openai":
        return OPENAI_API_KEY
    if provider == "elevenlabs":
        return ELEVENLABS_API_KEY or TTS_API_KEY
    return ""


def require_key_if_needed(service: str, provider: str, api_key: str) -> None:
    if provider in KEYED_PROVIDERS and not api_key:
        provider_env = {
            "openai": "OPENAI_API_KEY",
            "sarvam": "SARVAM_API_KEY",
            "elevenlabs": "ELEVENLABS_API_KEY",
        }[provider]
        extra = f" or {provider_env}"
        env_names = f"{service.upper()}_API_KEY{extra}"
        raise ProviderConfigError(
            service,
            provider,
            f"{service.upper()} provider {provider!r} requires an API key. "
            f"Pass {service}_api_key in room metadata or set {env_names}.",
        )


def openai_base_url() -> str:
    return OPENAI_BASE_URL or "https://api.openai.com/v1"


def elevenlabs_base_url() -> str:
    return ELEVENLABS_BASE_URL or "https://api.elevenlabs.io/v1"


def log_client_selected(
    service: str,
    provider: str,
    *,
    overridden: bool,
    has_api_key: bool,
) -> None:
    # Do not log api_key / *_api_key — client-provided keys must never land
    # in log files or observability tooling.
    logger.info(
        "inference_client_selected",
        extra={
            "event": "inference_client_selected",
            "service": service,
            "provider": provider,
            "overridden": overridden,
            "has_api_key": has_api_key,
        },
    )
