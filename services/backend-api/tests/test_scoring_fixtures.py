"""Fixture suite: generic/buzzword answers vs. deep technical answers.

Proves the Scoring Engine's LLM-verdict path (and its capped keyword/word-count
fallback) never rewards fluent-but-empty phrasing with a high strength rating.
See the score-mapping threshold table in AnswerEvaluation's docstring
(services/voice-agent/products/interviewer/validator.py) for the expected bands.
"""
from __future__ import annotations

import pytest

from brain.scoring import _strength_for_answer

EXPECTED_EVIDENCE = ["kafka consumer tuning", "measured latency improvement"]

GENERIC_ANSWERS = [
    "I handled it and there was a trade-off, but overall it worked out well.",
    "I was responsible for that and we followed best practices throughout.",
    "We worked closely with the team and optimized performance in general.",
]

DEEP_ANSWERS = [
    "I set the kafka consumer tuning to raise max.poll.records to 200, which "
    "reduced measured latency improvement from 420ms to 90ms p99.",
]


@pytest.mark.parametrize("text", GENERIC_ANSWERS)
def test_generic_answers_never_score_strong_via_keyword_fallback(text: str) -> None:
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=None)
    assert strength != "strong"


@pytest.mark.parametrize("text", GENERIC_ANSWERS)
def test_generic_answers_score_low_when_llm_marks_surface(text: str) -> None:
    record = {"final_transcript": text, "answer_evaluation": {"technical_substance": "surface"}}
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=record)
    assert strength == "weak"


@pytest.mark.parametrize("text", DEEP_ANSWERS)
def test_deep_answers_score_strong_when_llm_marks_deep(text: str) -> None:
    record = {"final_transcript": text, "answer_evaluation": {"technical_substance": "deep"}}
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=record)
    assert strength == "strong"


def test_incorrect_answer_scores_weak_even_if_fluent_and_detailed() -> None:
    text = DEEP_ANSWERS[0]
    record = {"final_transcript": text, "answer_evaluation": {"technical_substance": "incorrect"}}
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=record)
    assert strength == "weak"


def test_deep_but_factually_wrong_answer_scores_weak_not_strong() -> None:
    """A detailed answer that states a false fact must not earn 'strong'."""
    text = DEEP_ANSWERS[0]
    record = {
        "final_transcript": text,
        "answer_evaluation": {"technical_substance": "deep", "factually_correct": False},
    }
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=record)
    assert strength == "weak"


def test_deep_and_factually_correct_still_scores_strong() -> None:
    text = DEEP_ANSWERS[0]
    record = {
        "final_transcript": text,
        "answer_evaluation": {"technical_substance": "deep", "factually_correct": True},
    }
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=record)
    assert strength == "strong"


@pytest.mark.parametrize("text", ["", "   ", "ok"])
def test_empty_or_short_answer_does_not_crash(text: str) -> None:
    strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=None)
    assert strength == "weak"


def test_missing_or_malformed_evaluation_falls_back_safely() -> None:
    text = GENERIC_ANSWERS[0]
    for bad_record in (None, {}, {"answer_evaluation": "not a dict"}, {"answer_evaluation": {}}):
        strength = _strength_for_answer(text, EXPECTED_EVIDENCE, answer_evaluation=bad_record)
        assert strength in {"weak", "partial", "sufficient"}
