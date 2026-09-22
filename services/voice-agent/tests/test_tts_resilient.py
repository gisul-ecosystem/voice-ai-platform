from __future__ import annotations

import pytest

from clients.errors import ServiceUnavailableError
from clients.tts.resilient import ResilientTts


class Primary:
    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str) -> bytes:
        self.calls += 1
        raise ServiceUnavailableError("tts", "402 Payment Required")


class Fallback:
    async def synthesize(self, text: str) -> bytes:
        return b"RIFF-fallback"


@pytest.mark.asyncio
async def test_resilient_tts_fails_over_on_payment_required() -> None:
    tts = ResilientTts(Primary(), Fallback(), pin_voice=False)
    audio = await tts.synthesize("Hello")
    assert audio == b"RIFF-fallback"
    second = await tts.synthesize("Again")
    assert second == b"RIFF-fallback"
    assert tts._primary.calls == 2


class FlakyPrimary:
    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str) -> bytes:
        self.calls += 1
        if self.calls == 1:
            raise ServiceUnavailableError("tts", "429 Too Many Requests")
        return b"RIFF-ok"


@pytest.mark.asyncio
async def test_resilient_tts_pins_voice_and_does_not_switch_provider() -> None:
    tts = ResilientTts(Primary(), Fallback())
    with pytest.raises(ServiceUnavailableError):
        await tts.synthesize("Hello")
    assert tts._primary.calls == 2


@pytest.mark.asyncio
async def test_resilient_tts_retries_primary_once_when_voice_is_pinned() -> None:
    primary = FlakyPrimary()
    tts = ResilientTts(primary, Fallback(), pin_voice=True)
    audio = await tts.synthesize("Hello")
    assert audio == b"RIFF-ok"
    assert primary.calls == 2
