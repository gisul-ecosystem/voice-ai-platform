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
from clients.tts.voice_policy import ResolvedVoicePolicy
from livekit_adapters import LaptopLLM, LaptopSTT, LaptopTTS


@dataclass(frozen=True)
class InferenceClients:
    llm: Any
    stt: Any
    tts: Any


def load_inference_clients(
    ctx: Any,
    logger: logging.Logger,
    *,
    voice_policy: ResolvedVoicePolicy | dict[str, Any] | None = None,
) -> InferenceClients:
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
        llm_client, stt_client, tts_client = clients_from_overrides(
            overrides,
            voice_policy=voice_policy,
        )
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
        # Allow natural breathing pauses during technical answers before concluding the turn.
        vad=silero.VAD.load(min_speech_duration=0.35, min_silence_duration=1.2),
        stt=LaptopSTT(client=clients.stt),
        llm=LaptopLLM(client=clients.llm),
        tts=LaptopTTS(client=clients.tts),
        # Publish agent speech text so the live transcript can show interviewer lines.
        use_tts_aligned_transcript=True,
        # Allow natural barge-in if candidate starts speaking or correcting.
        allow_interruptions=True,
        min_interruption_duration=1.2,
        min_interruption_words=3,
        min_endpointing_delay=1.0,
        max_endpointing_delay=2.5,
        resume_false_interruption=True,
        false_interruption_timeout=2.0,
        # Preemptive drafting made the agent commit to replying on partial/paused
        # speech before the candidate finished their sentence — disabled so the
        # full final utterance reaches the LLM before a reply is generated.
        preemptive_generation=False,
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
