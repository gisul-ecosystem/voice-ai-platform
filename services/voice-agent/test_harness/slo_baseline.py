#!/usr/bin/env python3
"""First-pass SLO measurement harness (docs/interviewer_slos.md).

Records composed speech-end→first-audio budget math and prompt-size checks.
Does not call paid providers. Live staging samples are pasted into
docs/slo_baseline_record.md after a real interview.

Usage:
  cd services/voice-agent
  set PYTHONPATH=.
  python test_harness/slo_baseline.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from products.interviewer.flow import InterviewFlow
from products.interviewer.latency import (
    LLM_TTFB_BUDGET_P50_MS,
    SPEECH_END_TO_FIRST_AUDIO_P50_MS,
    SPEECH_END_TO_FIRST_AUDIO_P95_MS,
    TURN_PROMPT_BUDGET_CHARS,
    prompt_within_budget,
    speech_end_to_first_audio_ms,
    summarize_first_audio,
)
from tests.test_interview_policy_flow import FakeLlm, _definition


def _composed_budget_row() -> dict:
    composed = speech_end_to_first_audio_ms(
        endpointing_ms=350,
        stt_ms=200,
        llm_ttfb_ms=LLM_TTFB_BUDGET_P50_MS,
        tts_ttfb_ms=200,
    )
    return {
        "composed_ms": composed,
        "meets_p50_target": composed <= SPEECH_END_TO_FIRST_AUDIO_P50_MS,
        "meets_p95_launch": composed <= SPEECH_END_TO_FIRST_AUDIO_P95_MS,
        "breakdown_ms": {
            "endpointing": 350,
            "stt": 200,
            "llm_ttfb": LLM_TTFB_BUDGET_P50_MS,
            "tts_ttfb": 200,
        },
    }


def _prompt_budget_row() -> dict:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        job_description="Backend engineer owning APIs and reliability.",
        resume_text="Built checkout APIs in Python and cut p95 latency.",
        initial_phase_index=2,
    )
    prompt, _ = flow._structured_system_prompt(
        "I owned the checkout service and cut latency.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )
    return {
        "prompt_chars": len(prompt),
        "budget_chars": TURN_PROMPT_BUDGET_CHARS,
        "within_budget": prompt_within_budget(prompt),
    }


def main() -> None:
    fixture_samples = [900, 1000, 1050, 1100, 1150, 1180, 1250, 1400]
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "environment": "local_fixture",
        "source": "docs/interviewer_slos.md",
        "targets_ms": {
            "speech_end_to_first_audio_p50": SPEECH_END_TO_FIRST_AUDIO_P50_MS,
            "speech_end_to_first_audio_p95": SPEECH_END_TO_FIRST_AUDIO_P95_MS,
            "llm_ttfb_p50_share": LLM_TTFB_BUDGET_P50_MS,
        },
        "composed_budget": _composed_budget_row(),
        "prompt_budget": _prompt_budget_row(),
        "fixture_first_audio_summary": summarize_first_audio(fixture_samples),
        "live_staging": {
            "note": (
                "Paste stage_latency / speech-end→audio samples from staging "
                "worker logs into docs/slo_baseline_record.md after a live invite."
            ),
            "samples_ms": [],
        },
    }
    print(json.dumps(report, indent=2))
    ok = (
        report["composed_budget"]["meets_p95_launch"]
        and report["prompt_budget"]["within_budget"]
        and report["fixture_first_audio_summary"]["meets_p95"]
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
