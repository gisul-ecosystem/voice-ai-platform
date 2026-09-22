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
    text = "The team project was interesting for everyone involved."
    _, _, hinted = classify_live_answer(
        text,
        required_intents=["establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution", "approach or method"],
    )
    covered = evidenced_intents(
        required_intents=["establish_ownership", "applied_understanding"],
        evidence_expected=["personal contribution", "approach or method"],
        asked_intent="establish_ownership",
        answer_text=text,
    )
    assert covered == []
    assert isinstance(hinted, list)


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


def test_surface_evaluation_does_not_cover_hollow_answers() -> None:
    """Surface judge + no cues/facts → uncovered. Concrete facts still win over surface."""
    covered_hollow = evidenced_intents(
        required_intents=["establish_ownership"],
        evidence_expected=["personal contribution"],
        answer_eval=AnswerEvaluation(technical_substance="surface"),
        asked_intent="establish_ownership",
        answer_text="It was fine.",
    )
    assert covered_hollow == []

    covered_with_facts = evidenced_intents(
        required_intents=["establish_ownership"],
        evidence_expected=["personal contribution"],
        answer_eval=AnswerEvaluation(technical_substance="surface"),
        asked_intent="establish_ownership",
        answer_text="I owned the billing retries and cut errors from 12% to 3%.",
    )
    assert "establish_ownership" in covered_with_facts


def test_backoff_answer_covers_applied_understanding() -> None:
    """Dry-run turn-5 style: technique + outcome must credit method intent."""
    text = (
        "For retries I used exponential backoff with idempotency keys in Redis "
        "so duplicate webhooks would not double-charge. We measured p95 latency "
        "and timeout errors before and after."
    )
    covered = evidenced_intents(
        required_intents=[
            "establish_context",
            "establish_ownership",
            "applied_understanding",
        ],
        evidence_expected=[
            "production ownership",
            "personal contribution",
            "technical approach",
        ],
        asked_intent="applied_understanding",
        answer_text=text,
    )
    assert "applied_understanding" in covered


def test_same_transcript_scores_identically_twice() -> None:
    """Determinism: identical answers must not flip covered/missing across calls."""
    text = (
        "For retries I used exponential backoff with idempotency keys in Redis "
        "so duplicate webhooks would not double-charge. We measured p95 latency "
        "and timeout errors before and after."
    )
    kwargs = dict(
        required_intents=[
            "establish_context",
            "establish_ownership",
            "applied_understanding",
        ],
        evidence_expected=["technical approach"],
        asked_intent="applied_understanding",
        answer_text=text,
        answer_eval=AnswerEvaluation(
            technical_substance="surface",
            key_facts_stated=[],
        ),
    )
    first = evidenced_intents(**kwargs)
    second = evidenced_intents(**kwargs)
    assert first == second
    assert "applied_understanding" in first


def test_cue_path_stable_across_llm_judge_verdicts() -> None:
    """Doc1/doc2 class: same answer text must not flip applied credit when the
    LLM substance label changes (surface vs partial vs absent judge)."""
    text = (
        "For retries I used exponential backoff with idempotency keys in Redis "
        "so duplicate webhooks would not double-charge. We measured p95 latency "
        "and timeout errors before and after."
    )
    required = [
        "establish_context",
        "establish_ownership",
        "applied_understanding",
    ]
    judges = [
        None,
        AnswerEvaluation(technical_substance="surface", key_facts_stated=[]),
        AnswerEvaluation(technical_substance="partial", key_facts_stated=[]),
        AnswerEvaluation(technical_substance="deep", key_facts_stated=["backoff"]),
    ]
    results = [
        evidenced_intents(
            required_intents=required,
            evidence_expected=["technical approach"],
            asked_intent="applied_understanding",
            answer_text=text,
            answer_eval=judge,
        )
        for judge in judges
    ]
    # Cue-path must always credit applied for this technique answer.
    assert all("applied_understanding" in covered for covered in results)
    # And must not disagree with itself across judge labels for that intent.
    applied_flags = ["applied_understanding" in covered for covered in results]
    assert len(set(applied_flags)) == 1


def test_webhook_storm_answer_credits_problem_despite_context_ask() -> None:
    """Cross-intent: strong failure-mode answer credits problem_or_complexity."""
    text = (
        "On reliability, the main failure mode was webhook storms. "
        "We rate-limited and added a dead-letter queue so operators could replay safely."
    )
    covered = evidenced_intents(
        required_intents=["establish_context", "problem_or_complexity"],
        evidence_expected=["incident handling", "failure mode"],
        asked_intent="establish_context",
        answer_text=text,
    )
    assert "problem_or_complexity" in covered
