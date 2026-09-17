"""Shared LiveKit session construction for all voice products."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from livekit.agents import AgentSession
from livekit.plugins import silero

from clients.errors import ProviderConfigError
from clients.inference import (
    clients_from_overrides,
    inference_overrides_from_metadata,
    parse_room_metadata,
)
from livekit_adapters import LaptopLLM, LaptopSTT, LaptopTTS


@dataclass(frozen=True)
class InferenceClients:
    llm: Any
    stt: Any
    tts: Any


def load_inference_clients(ctx: Any, logger: logging.Logger) -> InferenceClients:
    """Resolve room-level provider choices before the first conversation turn."""
    job = getattr(ctx, "job", None)
    raw_metadata = (
        getattr(job, "metadata", None)
        or getattr(ctx.room, "metadata", None)
        or ""
    )
    overrides = inference_overrides_from_metadata(
        parse_room_metadata(raw_metadata)
    )
    try:
        llm_client, stt_client, tts_client = clients_from_overrides(overrides)
    except ProviderConfigError:
        logger.exception(
            "inference_config_invalid",
            extra={"event": "inference_config_invalid", **overrides.log_safe()},
        )
        raise
    return InferenceClients(llm=llm_client, stt=stt_client, tts=tts_client)


def build_agent_session(clients: InferenceClients) -> AgentSession:
    """Construct the shared STT → LLM → TTS LiveKit pipeline."""
    return AgentSession(
        vad=silero.VAD.load(min_speech_duration=0.35, min_silence_duration=0.4),
        stt=LaptopSTT(client=clients.stt),
        llm=LaptopLLM(client=clients.llm),
        tts=LaptopTTS(client=clients.tts),
        # Audio can start as soon as ElevenLabs returns. Transcript UI only
        # renders LiveKit segments marked final.
        use_tts_aligned_transcript=False,
        # Streaming STT supplies interim words, so barge-in waits for real
        # speech (~2 words) instead of coughs cancelling the question.
        allow_interruptions=True,
        min_interruption_duration=0.7,
        min_interruption_words=2,
        min_endpointing_delay=0.4,
        max_endpointing_delay=2.0,
    )


def attach_session_metrics(session: AgentSession, logger: logging.Logger) -> None:
    """Keep the existing stage metric event shape shared by both products."""

    @session.on("metrics_collected")
    def _on_metrics(ev: Any) -> None:
        metrics = getattr(ev, "metrics", ev)
        kind = getattr(metrics, "type", type(metrics).__name__)
        duration_ms = None
        if hasattr(metrics, "duration"):
            duration_ms = round(float(metrics.duration) * 1000, 1)
        logger.info(
            "turn_stage_metrics",
            extra={
                "event": "turn_stage_metrics",
                "stage": kind,
                "latency_ms": duration_ms,
            },
        )
