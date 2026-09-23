"""Milestone 5 / PBI-A3: session-pinned TTS voice + preflight."""
from __future__ import annotations

import pytest

from clients.errors import ServiceUnavailableError
from clients.tts.resilient import ResilientTts
from clients.tts.voice_policy import (
    resolve_voice_policy,
    run_tts_preflight,
    synthesize_same_voice,
    voice_id_of,
)


class PinnedPrimary:
    def __init__(self, voice_id: str = "pinned-voice") -> None:
        self.voice_id = voice_id
        self.calls = 0
        self.fail_times = 0

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.calls += 1
        if voice is not None and voice != self.voice_id:
            raise AssertionError(f"voice override attempted: {voice}")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ServiceUnavailableError("tts", "429 rate limit")
        return b"RIFF-ok"


class Fallback:
    def __init__(self) -> None:
        self.voice_id = "other-voice"
        self.calls = 0

    async def synthesize(self, text: str, **kwargs) -> bytes:
        self.calls += 1
        return b"RIFF-fallback"


def test_resolve_voice_policy_defaults_pin() -> None:
    policy = resolve_voice_policy({"provider": "elevenlabs", "voice_id": "abc123"})
    assert policy.voice_id == "abc123"
    assert policy.pin_voice is True
    assert policy.recovery_action == "pause"
    assert policy.preflight_required is True


def test_resolve_voice_policy_end_recovery() -> None:
    policy = resolve_voice_policy(
        {
            "provider": "elevenlabs",
            "voice_id": "abc123",
            "fallback_policy": "same_voice_retry_then_end",
        }
    )
    assert policy.recovery_action == "end"
    assert policy.pin_voice is True


@pytest.mark.asyncio
async def test_pinned_resilient_never_switches_provider() -> None:
    primary = PinnedPrimary()
    fallback = Fallback()
    tts = ResilientTts(primary, fallback, pin_voice=True)
    with pytest.raises(ServiceUnavailableError):
        # First attempt + same-voice retry both fail; must not call fallback.
        primary.fail_times = 2
        await tts.synthesize("Hello")
    assert fallback.calls == 0
    assert primary.calls == 2
    assert voice_id_of(tts) == "pinned-voice"


@pytest.mark.asyncio
async def test_same_voice_retry_keeps_voice_id() -> None:
    primary = PinnedPrimary()
    primary.fail_times = 1
    audio = await synthesize_same_voice(primary, "Hello", attempts=2)
    assert audio == b"RIFF-ok"
    assert primary.calls == 2
    assert primary.voice_id == "pinned-voice"


@pytest.mark.asyncio
async def test_preflight_fails_closed_without_switching_voice() -> None:
    class Dead:
        voice_id = "pinned-voice"

        async def synthesize(self, text: str, **kwargs) -> bytes:
            raise ServiceUnavailableError("tts", "402 Payment Required")

    policy = resolve_voice_policy(
        {"provider": "elevenlabs", "voice_id": "pinned-voice", "preflight_required": True}
    )
    with pytest.raises(ServiceUnavailableError):
        await run_tts_preflight(Dead(), policy, session_id="ses_test")


@pytest.mark.asyncio
async def test_preflight_ok_logs_pinned_voice() -> None:
    policy = resolve_voice_policy(
        {"provider": "elevenlabs", "voice_id": "pinned-voice", "preflight_required": True}
    )
    await run_tts_preflight(PinnedPrimary(), policy, session_id="ses_ok")
