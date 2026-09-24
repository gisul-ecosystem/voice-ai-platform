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
from clients.tts.voice_policy import ResolvedVoicePolicy, resolve_voice_policy

logger = logging.getLogger("voice-agent.inference")

INFERENCE_META_KEYS = (
    "llm_provider",
    "stt_provider",
    "tts_provider",
)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class InferenceOverrides:
    llm_provider: str | None = None
    stt_provider: str | None = None
    tts_provider: str | None = None

    def log_safe(self) -> dict[str, Any]:
        return {
            "llm_provider": self.llm_provider,
            "stt_provider": self.stt_provider,
            "tts_provider": self.tts_provider,
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
        stt_provider=_opt_str(meta.get("stt_provider")),
        tts_provider=_opt_str(meta.get("tts_provider")),
    )


def clients_from_overrides(
    overrides: InferenceOverrides,
    *,
    voice_policy: ResolvedVoicePolicy | dict[str, Any] | None = None,
) -> tuple[OpenAICompatLlm, SttClient, TtsClient]:
    """Build LLM/STT/TTS clients. Raises ProviderConfigError before the first turn."""
    raw_policy: dict[str, Any] | None
    if isinstance(voice_policy, ResolvedVoicePolicy):
        raw_policy = {
            "provider": voice_policy.provider,
            "voice_id": voice_policy.voice_id,
            "model_id": voice_policy.model_id,
            "stability": voice_policy.stability,
            "speed": voice_policy.speed,
            "fallback_policy": voice_policy.fallback_policy,
            "preflight_required": voice_policy.preflight_required,
        }
    elif isinstance(voice_policy, dict):
        raw_policy = voice_policy
    else:
        raw_policy = None

    # Session tts_provider override must re-resolve model/voice defaults.
    # Otherwise an elevenlabs-published model_id (e.g. eleven_turbo_v2_5) is
    # sent to OpenAI /audio/speech and returns 404.
    policy = resolve_voice_policy(
        raw_policy,
        provider_override=overrides.tts_provider,
    )
    llm = get_llm_client(overrides.llm_provider)
    stt = get_stt_client(overrides.stt_provider)
    tts = get_tts_client(
        overrides.tts_provider or policy.provider,
        voice_policy=policy,
    )
    logger.info(
        "inference_overrides_applied",
        extra={
            "event": "inference_overrides_applied",
            **overrides.log_safe(),
            "tts_provider_resolved": policy.provider,
            "tts_voice_id": policy.voice_id,
            "tts_model_id": policy.model_id,
            "tts_fallback_policy": policy.fallback_policy,
        },
    )
    return llm, stt, tts
