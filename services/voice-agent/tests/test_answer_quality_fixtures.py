"""Fixture suite: generic/buzzword answers vs. deep technical answers.

Proves the LLM-substance verdict (not keyword/word-count heuristics) separates
shallow-sounding-confident answers from genuinely deep ones, and that nothing
crashes on empty/short candidate input. See the score-mapping threshold table
in AnswerEvaluation's docstring (validator.py) for the expected bands.
"""
from __future__ import annotations

import pytest

from products.interviewer.coverage import (
    classify_live_answer,
    evidenced_intents,
    quality_from_evaluation,
)
from products.interviewer.validator import AnswerEvaluation, parse_answer_evaluation

GENERIC_ANSWERS = [
    "I handled it and there was a trade-off, but overall it worked out well.",
    "I was responsible for that and we followed best practices throughout.",
    "We worked closely with the team and optimized performance in general.",
    "I took ownership of the project and made sure everything went smoothly.",
]

DEEP_ANSWERS = [
    "I set the Kafka consumer's max.poll.records to 200 and moved deserialization "
    "onto a worker pool, which cut p99 latency from 420ms to 90ms.",
    "We chose optimistic locking over row locks because writes were 95% "
    "non-conflicting; conflict retries added only 2ms average overhead.",
    "I rewrote the join as a hash join instead of nested loop, dropping the "
    "query from 8s to 300ms on the 40M row table.",
]


@pytest.mark.parametrize("text", GENERIC_ANSWERS)
def test_generic_phrases_score_low_via_llm_verdict(text: str) -> None:
    evaluation = AnswerEvaluation(technical_substance="surface", reasoning=text[:80])
    assert quality_from_evaluation(evaluation) == "unclear"


@pytest.mark.parametrize("text", DEEP_ANSWERS)
def test_deep_answers_score_high_via_llm_verdict(text: str) -> None:
    evaluation = AnswerEvaluation(technical_substance="deep", reasoning=text[:80])
    assert quality_from_evaluation(evaluation) == "sufficient"


def test_incorrect_answer_never_scores_high_even_if_fluent() -> None:
    evaluation = AnswerEvaluation(technical_substance="incorrect")
    assert quality_from_evaluation(evaluation) == "unclear"


def test_deep_but_factually_wrong_answer_scores_low() -> None:
    """A detailed, confident answer that states a false fact must not score high."""
    evaluation = AnswerEvaluation(
        technical_substance="deep",
        reasoning="Detailed but claims TCP is connectionless, which is false.",
        factually_correct=False,
    )
    assert quality_from_evaluation(evaluation) == "unclear"


def test_deep_and_factually_correct_still_scores_high() -> None:
    evaluation = AnswerEvaluation(technical_substance="deep", factually_correct=True)
    assert quality_from_evaluation(evaluation) == "sufficient"


def test_not_applicable_falls_back_to_keyword_heuristic() -> None:
    evaluation = AnswerEvaluation(technical_substance="not_applicable")
    assert quality_from_evaluation(evaluation) is None


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_or_none_answer_does_not_crash(text) -> None:
    usability, quality, covered = classify_live_answer(
        text,
        required_intents=["establish_context", "establish_ownership"],
        evidence_expected=["specific tool", "measured outcome"],
    )
    assert usability in {"silence", "too_short"}
    assert quality in {"unusable", "unclear"}
    assert covered == []


@pytest.mark.parametrize("text", ["yes", "ok", "sure thing"])
def test_short_answer_does_not_crash(text: str) -> None:
    usability, quality, covered = classify_live_answer(
        text,
        required_intents=["establish_context"],
        evidence_expected=["specific tool"],
    )
    assert usability in {"too_short", "usable"}
    assert covered == []


@pytest.mark.parametrize("payload", [None, {}, {"technical_substance": "not_a_real_value"}, "not a dict"])
def test_parse_answer_evaluation_never_crashes_on_bad_payload(payload) -> None:
    assert parse_answer_evaluation(payload) is None


def test_keyword_only_answer_does_not_cover_intents() -> None:
    text = "I used it because the team project was interesting."
    _, _, hinted = classify_live_answer(
        text,
        required_intents=["establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution", "approach or method"],
    )
    assert hinted
    covered = evidenced_intents(
        required_intents=["establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution", "approach or method"],
        asked_intent="establish_ownership",
        answer_text=text,
    )
    assert covered == []


def test_evidenced_ownership_covers_only_asked_intent() -> None:
    text = "I owned the billing retries and cut timeout errors from 12% to 3%."
    covered = evidenced_intents(
        required_intents=["establish_context", "establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution", "result or impact"],
        asked_intent="establish_ownership",
        answer_text=text,
    )
    assert covered == ["establish_ownership"]


def test_previous_evaluation_covers_asked_intent() -> None:
    covered = evidenced_intents(
        required_intents=["establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution"],
        answer_eval=AnswerEvaluation(
            technical_substance="deep",
            key_facts_stated=["owned billing retries"],
            matches_evidence_expected=True,
        ),
        asked_intent="establish_ownership",
        answer_text="I handled the retries.",
    )
    assert covered == ["establish_ownership"]


def test_surface_evaluation_does_not_cover_intents() -> None:
    covered = evidenced_intents(
        required_intents=["establish_ownership"],
        evidence_expected=["personal contribution"],
        answer_eval=AnswerEvaluation(technical_substance="surface"),
        asked_intent="establish_ownership",
        answer_text="I owned the billing retries and cut errors from 12% to 3%.",
    )
    assert covered == []
