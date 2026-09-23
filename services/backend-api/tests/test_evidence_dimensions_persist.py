"""Evidence dimensions must survive the trip from the agent into the scorecard.

They were silently dropped for a while: the voice agent sent them, the backend
model ignored unknown fields, and nothing downstream noticed.
"""
from __future__ import annotations

from models.brain import AnswerEvaluation, CompetencyScore


def test_backend_model_keeps_evidence_dimensions() -> None:
    payload = {
        "technical_substance": "deep",
        "key_facts_stated": ["9k events/sec"],
        "reasoning": "Explained the invariant and stated the cost.",
        "matches_evidence_expected": True,
        "needs_clarification": False,
        "factually_correct": True,
        "slots_demonstrated": ["mechanism", "complexity_or_cost"],
        "slots_claimed": ["optimization"],
        "contradicts_earlier": False,
    }
    parsed = AnswerEvaluation.model_validate(payload)

    assert parsed.slots_demonstrated == ["mechanism", "complexity_or_cost"]
    assert parsed.slots_claimed == ["optimization"]
    assert parsed.contradicts_earlier is False
    # Round-trips, so it persists rather than being dropped on the way to Mongo.
    assert parsed.model_dump()["slots_demonstrated"] == ["mechanism", "complexity_or_cost"]


def test_evaluation_without_dimensions_still_parses() -> None:
    legacy = AnswerEvaluation.model_validate({"technical_substance": "partial"})
    assert legacy.slots_demonstrated == []
    assert legacy.slots_claimed == []


def test_competency_score_carries_proven_dimensions() -> None:
    score = CompetencyScore(
        competency_id="dsa",
        rating=5,
        outcome="scored",
        proven_dimensions=["ownership", "mechanism"],
        claimed_dimensions=["optimization"],
    )
    assert score.proven_dimensions == ["ownership", "mechanism"]
    assert score.claimed_dimensions == ["optimization"]
