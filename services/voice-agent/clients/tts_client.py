"""TTS client -- default path is the Kokoro wrapper on Laptop 3.

Per-session provider/key overrides: clients.tts.get_tts_client(...)
"""
from __future__ import annotations

from clients.tts import get_tts_client


async def synthesize(text: str, voice: str | None = None) -> bytes:
    return await get_tts_client().synthesize(text, voice=voice)
