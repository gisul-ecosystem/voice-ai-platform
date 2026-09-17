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
        vad=silero.VAD.load(min_speech_duration=0.5, min_silence_duration=0.5),
        stt=LaptopSTT(client=clients.stt),
        llm=LaptopLLM(client=clients.llm),
        tts=LaptopTTS(client=clients.tts),
        use_tts_aligned_transcript=False,
        # Yield instantly if the candidate talks over Aaptor, like a real interviewer,
        # but require a deliberate interruption (not a stray word) before cutting off.
        allow_interruptions=True,
        min_interruption_duration=2.0,
        min_interruption_words=4,
        min_endpointing_delay=0.5,
        max_endpointing_delay=2.5,
        resume_false_interruption=True,
        false_interruption_timeout=1.5,
        # Start drafting the reply as soon as speech looks finished, cutting dead air.
        preemptive_generation=True,
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
