"""Latency budgets for the live interviewer turn path.

Staging target from the readiness sprint: speech-end to first audio
p50 <= 1.2s and p95 <= 2.0s. CI checks prompt size and the composed
budget math; live p50/p95 need a staging run with real STT/LLM/TTS.
"""
from __future__ import annotations

from typing import Any

SPEECH_END_TO_FIRST_AUDIO_P50_MS = 1200.0
SPEECH_END_TO_FIRST_AUDIO_P95_MS = 2000.0
LLM_TTFB_BUDGET_P50_MS = 400.0
TURN_PROMPT_BUDGET_CHARS = 8500
PUBLISHED_CONTEXT_LIMIT_CHARS = 1800


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(100.0, p)) / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def speech_end_to_first_audio_ms(
    *,
    endpointing_ms: float,
    stt_ms: float,
    llm_ttfb_ms: float,
    tts_ttfb_ms: float,
) -> float:
    return float(endpointing_ms) + float(stt_ms) + float(llm_ttfb_ms) + float(tts_ttfb_ms)


def summarize_first_audio(samples_ms: list[float]) -> dict[str, Any]:
    p50 = percentile(samples_ms, 50)
    p95 = percentile(samples_ms, 95)
    return {
        "n": len(samples_ms),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "meets_p50": p50 <= SPEECH_END_TO_FIRST_AUDIO_P50_MS,
        "meets_p95": p95 <= SPEECH_END_TO_FIRST_AUDIO_P95_MS,
        "target_p50_ms": SPEECH_END_TO_FIRST_AUDIO_P50_MS,
        "target_p95_ms": SPEECH_END_TO_FIRST_AUDIO_P95_MS,
    }


def prompt_within_budget(prompt: str, *, limit: int = TURN_PROMPT_BUDGET_CHARS) -> bool:
    return len(prompt or "") <= limit
