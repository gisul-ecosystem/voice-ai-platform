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
    tts = ResilientTts(Primary(), Fallback())
    audio = await tts.synthesize("Hello")
    assert audio == b"RIFF-fallback"
    assert tts._use_fallback is True
    second = await tts.synthesize("Again")
    assert second == b"RIFF-fallback"
