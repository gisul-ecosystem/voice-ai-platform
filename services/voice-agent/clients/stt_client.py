"""STT client -- default path is the Nemotron wrapper on Laptop 2.

Per-session provider/key overrides: clients.stt.get_stt_client(...)
"""
from __future__ import annotations

from clients.stt import get_stt_client


async def transcribe(audio_bytes: bytes, filename: str = "chunk.wav") -> str:
    return await get_stt_client().transcribe(audio_bytes, filename=filename)
