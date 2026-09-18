"""Tests for Milestone 4 policy engine."""
from __future__ import annotations

from products.interviewer.policy import (
    ASK_BASELINE,
    CLOSE_INTERVIEW,
    MAP_CANDIDATE_BACKGROUND,
    MOVE_TO_NEXT_COMPETENCY,
    OPEN_INTERVIEW,
    PolicyState,
    classify_answer_usability,
    decide_next_action,
    outline_from_definition,
)


def _definition() -> dict:
    return {
        "definition_id": "idef_policy_test_01",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
        },
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "max_depth": 4,
                "max_probes": 2,
                "evidence_expected": ["context", "action", "result"],
            },
            {
                "id": "communication",
                "name": "Communication",
                "max_depth": 3,
                "max_probes": 2,
                "evidence_expected": ["clarity"],
            },
        ],
    }


def test_outline_is_breadth_first() -> None:
    outline = outline_from_definition(_definition())
    assert outline is not None
    names = [phase["name"] for phase in outline["phases"]]
    assert names[0] == "opening"
    assert names[1] == "candidate_map"
    assert "Problem solving" in names
    assert names[-1] == "closing"


def test_opening_and_map_are_forced_before_deep_dive() -> None:
    opening = decide_next_action(
        PolicyState(interviewer_turn_count=0, candidate_turn_count=0)
    )
    assert opening.action == OPEN_INTERVIEW
    assert opening.forced_flow_decision == "probe"

    mapping = decide_next_action(
        PolicyState(
            interviewer_turn_count=1,
            candidate_turn_count=1,
            phase_name="candidate_map",
        )
    )
    assert mapping.action == MAP_CANDIDATE_BACKGROUND
    assert mapping.allow_llm_decision is False


def test_baseline_then_depth_caps_force_advance() -> None:
    baseline = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="candidate_map",
            competency_id="problem_solving",
        )
    )
    assert baseline.action == ASK_BASELINE
    assert baseline.forced_flow_decision == "advance"

    capped = decide_next_action(
        PolicyState(
            interviewer_turn_count=5,
            candidate_turn_count=5,
            phase_name="Problem solving",
            competency_id="problem_solving",
            probe_count=2,
            max_probes=2,
            max_depth=4,
            has_uncovered_competencies=True,
        )
    )
    assert capped.action == MOVE_TO_NEXT_COMPETENCY
    assert capped.forced_flow_decision == "advance"


def test_hard_time_limit_closes() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=10,
            candidate_turn_count=10,
            phase_name="Problem solving",
            elapsed_seconds=35 * 60,
            hard_end_seconds=35 * 60,
        )
    )
    assert decision.action == CLOSE_INTERVIEW
    assert decision.forced_flow_decision == "close"


def test_answer_usability_classifier() -> None:
    assert classify_answer_usability("") == "silence"
    assert classify_answer_usability("ok") == "too_short"
    assert classify_answer_usability("I don't know") == "explicit_unknown"
    assert classify_answer_usability("I owned the billing API retries.") == "usable"
