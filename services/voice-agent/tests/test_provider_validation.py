"""Provider aliases must not silently fall through to the wrong service."""
from __future__ import annotations

import pytest

from clients.errors import ProviderConfigError
from clients.inference import inference_overrides_from_metadata
from clients.llm import get_llm_client
from clients.provider_util import normalize_provider
from clients.stt import get_stt_client
from clients.tts import get_tts_client


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("openai", "openai"),
        ("saaras:v3", "sarvam"),
        ("11labs", "elevenlabs"),
        ("kokoro", "self_hosted"),
    ],
)
def test_provider_aliases_are_preserved(raw: str, expected: str) -> None:
    assert normalize_provider(raw, fallback="self_hosted") == expected


@pytest.mark.parametrize(
    ("factory", "unsupported_provider"),
    [
        (get_llm_client, "sarvam"),
        (get_llm_client, "elevenlabs"),
        (get_stt_client, "elevenlabs"),
        (get_tts_client, "sarvam"),
    ],
)
def test_provider_cannot_silently_fall_through_to_self_hosted(
    factory, unsupported_provider: str
) -> None:
    with pytest.raises(ProviderConfigError):
        factory(
            provider_override=unsupported_provider,
            api_key_override="test-key",
        )


def test_room_metadata_cannot_override_provider_credentials() -> None:
    overrides = inference_overrides_from_metadata(
        {
            "llm_provider": "openai",
            "llm_api_key": "must-be-ignored",
            "stt_api_key": "must-be-ignored",
            "tts_api_key": "must-be-ignored",
        }
    )
    assert overrides.llm_provider == "openai"
    assert not hasattr(overrides, "llm_api_key")
