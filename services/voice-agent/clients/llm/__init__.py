"""LLM client factory. Env URL/model are the default; session can override provider+key."""
from __future__ import annotations

from clients.llm.openai_compat import OpenAICompatLlm, default_self_hosted_llm
from clients.provider_util import (
    log_client_selected,
    normalize_provider,
    openai_base_url,
    require_key_if_needed,
    resolve_api_key,
)
from clients.settings import LLM_MODEL_NAME, LLM_PROVIDER

LlmClient = OpenAICompatLlm

_DEFAULT: OpenAICompatLlm | None = None


def _openai_model() -> str:
    # Ollama tags (qwen3:4b-…) are rejected by OpenAI; keep env model when it looks official.
    if LLM_MODEL_NAME and ":" not in LLM_MODEL_NAME and not LLM_MODEL_NAME.lower().startswith("qwen"):
        return LLM_MODEL_NAME
    return "gpt-4o-mini"


def _build(provider: str, api_key: str) -> OpenAICompatLlm:
    if provider == "openai":
        return OpenAICompatLlm(
            base_url=openai_base_url(),
            model=_openai_model(),
            api_key=api_key,
        )
    return default_self_hosted_llm(api_key=api_key)


def get_llm_client(
    provider_override: str | None = None,
    api_key_override: str | None = None,
) -> OpenAICompatLlm:
    overridden = bool((provider_override or "").strip() or (api_key_override or "").strip())
    provider = normalize_provider(provider_override, fallback=LLM_PROVIDER)
    api_key = resolve_api_key("llm", provider, api_key_override)
    require_key_if_needed("llm", provider, api_key)

    if not overridden:
        global _DEFAULT
        if _DEFAULT is None:
            log_client_selected(
                "llm", provider, overridden=False, has_api_key=bool(api_key)
            )
            _DEFAULT = _build(provider, api_key)
        return _DEFAULT
    log_client_selected("llm", provider, overridden=True, has_api_key=bool(api_key))
    return _build(provider, api_key)
