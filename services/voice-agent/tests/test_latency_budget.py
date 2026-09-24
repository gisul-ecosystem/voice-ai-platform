"""Prompt-size and first-audio budget harness for P2 latency."""
from __future__ import annotations

from products.interviewer.flow import InterviewFlow
from products.interviewer.latency import (
    LLM_TTFB_BUDGET_P50_MS,
    SPEECH_END_TO_FIRST_AUDIO_P50_MS,
    SPEECH_END_TO_FIRST_AUDIO_P95_MS,
    TURN_PROMPT_BUDGET_CHARS,
    percentile,
    prompt_within_budget,
    speech_end_to_first_audio_ms,
    summarize_first_audio,
)
from tests.test_interview_policy_flow import FakeLlm, _definition


def _fat_definition() -> dict:
    definition = _definition()
    definition["job_intelligence"] = {
        "role": {"title": "AI Engineer", "domain": "AI/ML", "target_level": "mid"},
        "knowledge": [{"text": "Model evaluation and overfitting"}] * 20,
        "skills": [{"text": "Python and machine learning"}] * 20,
        "tools": [{"text": "scikit-learn"}] * 20,
        "responsibilities": [{"text": "Own production models"}] * 20,
        "raw_job_description": "Use algorithms, data structures, and model evaluation. " * 80,
    }
    definition["competencies"] = definition["competencies"] + [
        {
            "id": f"extra_{index}",
            "name": f"Extra competency {index}",
            "definition": "Long definition " * 40,
            "max_depth": 3,
            "max_probes": 2,
            "evidence_expected": ["context", "ownership", "result"],
        }
        for index in range(8)
    ]
    definition["question_ladders"] = definition["question_ladders"] + [
        {
            "competency_id": f"extra_{index}",
            "levels": [
                {
                    "depth": 1,
                    "intent": "establish_context",
                    "objective": "Assess technical communication",
                    "example_question": "How would you explain a model trade-off?",
                }
            ],
        }
        for index in range(8)
    ]
    return definition


def test_turn_prompt_stays_under_budget_with_fat_definition() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_fat_definition(),
        job_description="Use algorithms, data structures, and model evaluation. " * 80,
        resume_text="Built a machine learning classifier in Python. " * 40,
        candidate_profile={
            "claims": [
                {"claim_id": f"c{index}", "value": f"Built classifier variant {index}"}
                for index in range(20)
            ]
        },
        interviewer_turns=[f"question {index}" for index in range(10)],
        candidate_turns=[f"answer {index}" for index in range(10)],
        initial_phase_index=3,
    )
    prompt, _ = flow._structured_system_prompt(
        "I built a machine learning classifier in Python.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )
    assert prompt_within_budget(prompt)
    assert len(prompt) <= TURN_PROMPT_BUDGET_CHARS
    assert "Assess technical communication" not in prompt
    assert "Long definition" not in prompt
    assert "How would you explain a model trade-off?" not in prompt
    assert "question 9" in prompt
    assert "question 0" not in prompt
    assert "answer 9" in prompt
    assert "answer 0" not in prompt


def test_speech_end_to_first_audio_budget_math() -> None:
    composed = speech_end_to_first_audio_ms(
        endpointing_ms=350,
        stt_ms=200,
        llm_ttfb_ms=LLM_TTFB_BUDGET_P50_MS,
        tts_ttfb_ms=200,
    )
    assert composed <= SPEECH_END_TO_FIRST_AUDIO_P50_MS

    # Samples must clear launch gate p95 ≤ 1.5s (docs/interviewer_slos.md).
    samples = [900, 1000, 1050, 1100, 1150, 1180, 1250, 1400]
    summary = summarize_first_audio(samples)
    assert summary["n"] == 8
    assert summary["p50_ms"] <= SPEECH_END_TO_FIRST_AUDIO_P50_MS
    assert summary["p95_ms"] <= SPEECH_END_TO_FIRST_AUDIO_P95_MS
    assert summary["meets_p50"] is True
    assert summary["meets_p95"] is True
    assert summary["target_p95_ms"] == 1500.0


def test_percentile_is_interpolated() -> None:
    assert percentile([10, 20, 30, 40], 50) == 25.0
    assert percentile([100], 95) == 100.0
    assert percentile([], 50) == 0.0
