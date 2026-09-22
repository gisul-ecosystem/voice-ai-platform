"""The transcript-only scoring fallback must still honour the LLM verdict.

`_synthesize_qa_from_turns` runs when no brain Q/A rows exist for a session.
Before the verdict was carried on the turn, that path scored purely on word
count, so a fluent generic answer looked the same as a deep one.
"""
from __future__ import annotations

from brain.scoring import _strength_for_answer
from brain.scoring_service import _synthesize_qa_from_turns

EXPECTED_EVIDENCE = ["kafka consumer tuning", "measured latency improvement"]

GENERIC_ANSWER = "I handled it and there was a trade-off, but overall it worked out well."
DEEP_ANSWER = (
    "I raised max.poll.records to 200 for kafka consumer tuning, a measured "
    "latency improvement from 420ms to 90ms p99."
)


def _turns(answer_text: str, evaluation: dict | None) -> list[dict]:
    candidate_turn: dict = {
        "turn_id": "turn_b",
        "speaker": "candidate",
        "text": answer_text,
        "sequence_number": 2,
    }
    if evaluation is not None:
        candidate_turn["answer_evaluation"] = evaluation
    return [
        {
            "turn_id": "turn_a",
            "speaker": "agent",
            "text": "How did you tune that consumer?",
            "sequence_number": 1,
        },
        candidate_turn,
    ]


def test_synthesized_answer_carries_the_llm_verdict() -> None:
    _, answers = _synthesize_qa_from_turns(
        "ses_1234567890", _turns(DEEP_ANSWER, {"technical_substance": "deep"})
    )
    assert answers[0]["answer_evaluation"] == {"technical_substance": "deep"}
    assert _strength_for_answer(DEEP_ANSWER, EXPECTED_EVIDENCE, answers[0]) == "strong"


def test_generic_answer_scores_weak_when_verdict_says_surface() -> None:
    _, answers = _synthesize_qa_from_turns(
        "ses_1234567890", _turns(GENERIC_ANSWER, {"technical_substance": "surface"})
    )
    assert _strength_for_answer(GENERIC_ANSWER, EXPECTED_EVIDENCE, answers[0]) == "weak"


def test_verdict_drives_usability_instead_of_word_count() -> None:
    """A wordy but non-substantive turn is no longer 'usable' just for length."""
    _, answers = _synthesize_qa_from_turns(
        "ses_1234567890",
        _turns(GENERIC_ANSWER, {"technical_substance": "not_applicable"}),
    )
    assert answers[0]["usable"] is False
    assert answers[0]["usability"] == "too_short"


def test_word_count_fallback_still_applies_without_a_verdict() -> None:
    _, answers = _synthesize_qa_from_turns("ses_1234567890", _turns(DEEP_ANSWER, None))
    assert answers[0]["usable"] is True
    assert answers[0]["answer_evaluation"] is None
    # The capped heuristic must never reach "strong" on its own.
    assert _strength_for_answer(DEEP_ANSWER, EXPECTED_EVIDENCE, answers[0]) != "strong"


def test_malformed_verdict_on_turn_does_not_crash() -> None:
    turns = _turns(DEEP_ANSWER, None)
    turns[1]["answer_evaluation"] = "not a dict"
    _, answers = _synthesize_qa_from_turns("ses_1234567890", turns)
    assert answers[0]["answer_evaluation"] is None
