"""Same published role: two experience levels, thin answers stay unrated, completed scorecard."""
from __future__ import annotations

from brain.scoring import build_scorecard_bundle


def _definition() -> dict:
    return {
        "definition_id": "idef_live_quality_score_01",
        "scoring_policy": {"min_evidence_per_competency": 1},
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "importance": "high",
                "weight": 100,
                "evidence_expected": ["context", "action", "result"],
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "rubric": [
                    {
                        "rating": 1,
                        "description": "Cannot describe a real problem, action, or result",
                    },
                    {
                        "rating": 3,
                        "description": "Explains a relevant problem, the action taken, and a result",
                    },
                    {
                        "rating": 5,
                        "description": "Tradeoffs, measured impact, and a concrete retry timeout decision",
                    },
                ],
            }
        ],
    }


def _questions() -> list[dict]:
    return [
        {
            "question_id": "q1",
            "competency_id": "problem_solving",
            "intent": "establish_context",
            "text": "What problem did you solve?",
            "validator_ok": True,
        }
    ]


def test_same_role_scorecard_is_complete_with_excerpts() -> None:
    scorecard, evidence = build_scorecard_bundle(
        session_id="ses_live_quality_deep01",
        definition=_definition(),
        questions=_questions(),
        answers=[
            {
                "answer_id": "a1",
                "question_id": "q1",
                "turn_ids": ["turn_candidate_1"],
                "usable": True,
                "final_transcript": (
                    "I owned the billing timeout context. I implemented retries "
                    "and the result was lower latency for checkout."
                ),
                "answer_evaluation": {
                    "technical_substance": "deep",
                    "factually_correct": True,
                },
            }
        ],
        coverage={
            "problem_solving": {
                "status": "partial",
                "covered_intents": ["establish_context"],
                "missing_intents": ["establish_ownership", "applied_understanding"],
            }
        },
    )
    scored = scorecard.competencies[0]
    assert evidence
    assert scored.outcome == "scored"
    assert scored.rating in {3, 5}
    assert scored.excerpts
    assert scored.anchor
    assert "establish_ownership" in scored.missing_intents
    assert scorecard.human_review_status == "pending"
    assert scorecard.quality_metrics is not None


def test_thin_answer_stays_not_assessed_not_invented_fail() -> None:
    scorecard, evidence = build_scorecard_bundle(
        session_id="ses_live_quality_thin01",
        definition=_definition(),
        questions=_questions(),
        answers=[
            {
                "answer_id": "a1",
                "question_id": "q1",
                "turn_ids": ["turn_candidate_1"],
                "usable": True,
                "final_transcript": "I don't know.",
            }
        ],
    )
    scored = scorecard.competencies[0]
    assert scored.rating is None
    assert scored.outcome in {"not_assessed", "insufficient_evidence"}
    assert scored.rating not in {1, 2}
    assert scorecard.overall_recommendation == "insufficient_evidence"
    assert all(item.strength != "strong" for item in evidence)


def test_five_anchor_match_rates_five_not_four() -> None:
    scorecard, _evidence = build_scorecard_bundle(
        session_id="ses_live_quality_bars01",
        definition=_definition(),
        questions=_questions(),
        answers=[
            {
                "answer_id": "a1",
                "question_id": "q1",
                "turn_ids": ["turn_candidate_1"],
                "usable": True,
                "final_transcript": (
                    "I changed the retry timeout after measuring impact. "
                    "The tradeoffs were extra load versus fewer checkout failures."
                ),
                "answer_evaluation": {
                    "technical_substance": "deep",
                    "factually_correct": True,
                },
            }
        ],
    )
    scored = scorecard.competencies[0]
    assert scored.outcome == "scored"
    assert scored.rating == 5
    assert scored.anchor
    assert "tradeoff" in (scored.anchor or "").lower() or "impact" in (scored.anchor or "").lower()
