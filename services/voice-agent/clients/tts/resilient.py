"""Fall back to another TTS provider when the primary one is billed or down."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from clients.errors import ServiceUnavailableError

logger = logging.getLogger("voice-agent.tts")


def _should_failover(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "401",
            "402",
            "403",
            "429",
            "payment",
            "unauthorized",
            "quota",
            "paid_plan",
        )
    )


class ResilientTts:
    def __init__(self, primary, fallback, *, pin_voice: bool = True) -> None:
        self._primary = primary
        self._fallback = fallback
        self._pin_voice = pin_voice

    def __getattr__(self, name: str):
        return getattr(self._primary, name)

    async def synthesize(self, text: str, **kwargs) -> bytes:
        try:
            return await self._primary.synthesize(text, **kwargs)
        except ServiceUnavailableError as exc:
            if self._pin_voice:
                logger.warning(
                    "tts_primary_retry",
                    extra={"event": "tts_primary_retry", "error_type": type(exc).__name__},
                )
                return await self._primary.synthesize(text, **kwargs)
            if self._fallback is None or not _should_failover(exc):
                logger.warning(
                    "tts_pinned_no_failover",
                    extra={
                        "event": "tts_pinned_no_failover",
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            logger.warning(
                "tts_provider_failover",
                extra={"event": "tts_provider_failover", "error_type": type(exc).__name__},
            )
        return await self._fallback.synthesize(text, **kwargs)

    async def stream_synthesize(self, text: str, **kwargs) -> AsyncIterator[bytes]:
        stream = getattr(self._primary, "stream_synthesize", None)
        try:
            if stream is not None:
                async for chunk in stream(text, **kwargs):
                    yield chunk
                return
            audio = await self._primary.synthesize(text, **kwargs)
            if audio:
                yield audio
            return
        except ServiceUnavailableError as exc:
            if self._pin_voice:
                logger.warning(
                    "tts_primary_retry",
                    extra={"event": "tts_primary_retry", "error_type": type(exc).__name__},
                )
                retry_stream = getattr(self._primary, "stream_synthesize", None)
                if retry_stream is not None:
                    async for chunk in retry_stream(text, **kwargs):
                        yield chunk
                    return
                audio = await self._primary.synthesize(text, **kwargs)
                if audio:
                    yield audio
                return
            if self._fallback is None or not _should_failover(exc):
                logger.warning(
                    "tts_pinned_no_failover",
                    extra={
                        "event": "tts_pinned_no_failover",
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            logger.warning(
                "tts_provider_failover",
                extra={"event": "tts_provider_failover", "error_type": type(exc).__name__},
            )
        fallback_stream = getattr(self._fallback, "stream_synthesize", None)
        if fallback_stream is not None:
            async for chunk in fallback_stream(text, **kwargs):
                yield chunk
            return
        audio = await self._fallback.synthesize(text, **kwargs)
        if audio:
            yield audio
