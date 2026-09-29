"""Room-metadata inference overrides. Keys are never logged from this module."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from clients.llm import get_llm_client
from clients.llm.openai_compat import OpenAICompatLlm
from clients.stt import SttClient, get_stt_client
from clients.tts import TtsClient, get_tts_client

logger = logging.getLogger("voice-agent.inference")

INFERENCE_META_KEYS = (
    "llm_provider",
    "llm_api_key",
    "stt_provider",
    "stt_api_key",
    "tts_provider",
    "tts_api_key",
)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class InferenceOverrides:
    llm_provider: str | None = None
    llm_api_key: str | None = None
    stt_provider: str | None = None
    stt_api_key: str | None = None
    tts_provider: str | None = None
    tts_api_key: str | None = None

    def log_safe(self) -> dict[str, Any]:
        # Client-provided keys must never land in log files or observability tooling.
        return {
            "llm_provider": self.llm_provider,
            "stt_provider": self.stt_provider,
            "tts_provider": self.tts_provider,
            "llm_api_key_set": bool(self.llm_api_key),
            "stt_api_key_set": bool(self.stt_api_key),
            "tts_api_key_set": bool(self.tts_api_key),
        }


def parse_room_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("room_metadata_invalid", extra={"event": "room_metadata_invalid"})
        return {}
    return parsed if isinstance(parsed, dict) else {}


def inference_overrides_from_metadata(meta: dict[str, Any]) -> InferenceOverrides:
    return InferenceOverrides(
        llm_provider=_opt_str(meta.get("llm_provider")),
        llm_api_key=_opt_str(meta.get("llm_api_key")),
        stt_provider=_opt_str(meta.get("stt_provider")),
        stt_api_key=_opt_str(meta.get("stt_api_key")),
        tts_provider=_opt_str(meta.get("tts_provider")),
        tts_api_key=_opt_str(meta.get("tts_api_key")),
    )


def clients_from_overrides(
    overrides: InferenceOverrides,
) -> tuple[OpenAICompatLlm, SttClient, TtsClient]:
    """Build LLM/STT/TTS clients. Raises ProviderConfigError before the first turn."""
    llm = get_llm_client(overrides.llm_provider, overrides.llm_api_key)
    stt = get_stt_client(overrides.stt_provider, overrides.stt_api_key)
    tts = get_tts_client(overrides.tts_provider, overrides.tts_api_key)
    logger.info(
        "inference_overrides_applied",
        extra={"event": "inference_overrides_applied", **overrides.log_safe()},
    )
    return llm, stt, tts
