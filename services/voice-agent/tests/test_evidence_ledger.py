from __future__ import annotations

import json

from products.interviewer.evidence import (
    CONFIRMED,
    DEMONSTRATED,
    build_ledger,
    difficulty_profile,
    promote,
    slots_for_level,
    target_slot_brief,
)
from products.interviewer.policy import (
    PROBE_FOR_CONSISTENCY,
    PROBE_FOR_REASONING,
    MOVE_TO_NEXT_COMPETENCY,
    PolicyState,
    decide_next_action,
)
from products.interviewer.validator import parse_generated_question


def _definition() -> dict:
    return {
        "definition_id": "idef_evidence_01",
        "competencies": [
            {
                "id": "dsa",
                "name": "Data structures and algorithms",
                "importance": "high",
                "target_level": "mid",
            }
        ],
    }


def test_ledger_requires_technical_dimensions_not_star_steps() -> None:
    ledger = build_ledger(_definition())
    required = ledger["dsa"].required
    # The bar is mechanism/cost/trade-off, not "context, contribution, result".
    assert "mechanism" in required
    assert "complexity_or_cost" in required
    assert "tradeoff" in required


def test_seniority_changes_the_evidence_bar() -> None:
    assert "tradeoff" not in slots_for_level("intern")
    assert "optimization" not in slots_for_level("junior")
    assert "optimization" in slots_for_level("senior")


def test_naming_a_technique_is_a_claim_not_a_demonstration() -> None:
    ledger = build_ledger(_definition())
    # "I used a sliding window" names the approach but proves no mechanism.
    promote(ledger, competency_id="dsa", claimed=["approach", "mechanism"])
    entry = ledger["dsa"]
    assert entry.status_of("approach") == "claimed"
    assert entry.is_satisfied() is False
    # An unsupported claim is probed before an untouched dimension.
    slot, _ = target_slot_brief(entry)
    assert slot == "approach"

    promote(ledger, competency_id="dsa", demonstrated=["approach"])
    slot, instruction = target_slot_brief(entry)
    assert slot == "mechanism"
    assert "step by step" in instruction


def test_repeated_demonstration_confirms_a_slot() -> None:
    ledger = build_ledger(_definition())
    promote(ledger, competency_id="dsa", demonstrated=["mechanism"])
    assert ledger["dsa"].status_of("mechanism") == DEMONSTRATED
    promote(ledger, competency_id="dsa", demonstrated=["mechanism"])
    assert ledger["dsa"].status_of("mechanism") == CONFIRMED


def test_policy_probes_the_unproven_slot_instead_of_moving_on() -> None:
    # Intents all covered, but complexity was never demonstrated.
    state = PolicyState(
        candidate_turn_count=8,
        interviewer_turn_count=8,
        phase_name="Data structures and algorithms",
        competency_id="dsa",
        probe_count=2,
        max_depth=5,
        max_probes=4,
        missing_intents=[],
        target_slot="complexity_or_cost",
        has_uncovered_competencies=True,
    )
    decision = decide_next_action(state)
    assert decision.forced_flow_decision == "probe"
    assert decision.action == PROBE_FOR_REASONING
    assert decision.intent == "problem_or_complexity"
    assert "complexity_or_cost" in decision.reason


def test_satisfied_ledger_lets_the_interview_move_on() -> None:
    state = PolicyState(
        candidate_turn_count=8,
        interviewer_turn_count=8,
        phase_name="Data structures and algorithms",
        competency_id="dsa",
        probe_count=2,
        max_depth=5,
        max_probes=4,
        missing_intents=[],
        target_slot=None,
        coverage_complete=True,
        has_uncovered_competencies=True,
    )
    decision = decide_next_action(state)
    assert decision.action == MOVE_TO_NEXT_COMPETENCY


def test_model_reports_which_slots_an_answer_proved() -> None:
    raw = json.dumps(
        {
            "question": "What is the space cost of that sliding window, and what would you trade to halve it?",
            "competency_id": "dsa",
            "intent": "problem_or_complexity",
            "depth": 4,
            "answer_evaluation": {
                "technical_substance": "deep",
                "key_facts_stated": ["O(n) time", "sliding window"],
                "reasoning": "Explained the invariant and stated the complexity.",
                "matches_evidence_expected": True,
                "needs_clarification": False,
                "factually_correct": True,
                "slots_demonstrated": ["mechanism", "complexity_or_cost"],
                "slots_claimed": ["optimization"],
                "contradicts_earlier": False,
            },
        }
    )
    parsed = parse_generated_question(raw)
    assert parsed is not None
    evaluation = parsed.answer_evaluation
    assert evaluation is not None
    assert evaluation.slots_demonstrated == ["mechanism", "complexity_or_cost"]
    assert evaluation.slots_claimed == ["optimization"]


def test_unknown_slot_names_from_the_model_are_discarded() -> None:
    raw = json.dumps(
        {
            "question": "How does that work?",
            "answer_evaluation": {
                "technical_substance": "partial",
                "slots_demonstrated": ["mechanism", "vibes", "SYNERGY"],
            },
        }
    )
    parsed = parse_generated_question(raw)
    assert parsed is not None
    assert parsed.answer_evaluation is not None
    assert parsed.answer_evaluation.slots_demonstrated == ["mechanism"]


def test_difficulty_changes_the_evidence_bar() -> None:
    foundational = build_ledger(_definition(), difficulty="foundational")["dsa"]
    strategic = build_ledger(_definition(), difficulty="strategic")["dsa"]

    # Foundational stops at mechanism - it never demands cost or trade-offs.
    assert "complexity_or_cost" not in foundational.required
    assert "tradeoff" not in foundational.required
    assert "mechanism" in foundational.required

    assert "tradeoff" in strategic.required
    assert len(strategic.required) > len(foundational.required)


def test_unknown_difficulty_falls_back_to_applied() -> None:
    assert difficulty_profile("nonsense") == difficulty_profile("applied")
    assert difficulty_profile(None) == difficulty_profile("applied")


def test_difficulty_never_shortens_a_ledger_to_nothing() -> None:
    for name in ("foundational", "applied", "diagnostic", "strategic"):
        entry = build_ledger(_definition(), difficulty=name)["dsa"]
        assert entry.required, name


def test_contradiction_forces_a_consistency_probe() -> None:
    state = PolicyState(
        candidate_turn_count=6,
        interviewer_turn_count=6,
        phase_name="Data structures and algorithms",
        competency_id="dsa",
        probe_count=1,
        max_depth=5,
        max_probes=4,
        target_slot="mechanism",
        contradiction_pending=True,
    )
    decision = decide_next_action(state)
    assert decision.action == PROBE_FOR_CONSISTENCY
    assert decision.intent == "consistency_check"
    assert decision.forced_flow_decision == "probe"

    state.contradiction_pending = False
    assert decide_next_action(state).action != PROBE_FOR_CONSISTENCY
