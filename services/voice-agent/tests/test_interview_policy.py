"""Tests for Milestone 4 policy engine."""
from __future__ import annotations

from products.interviewer.policy import (
    ASK_BASELINE,
    CLARIFY_CURRENT_ANSWER,
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
            phase_name="opening",
        )
    )
    assert mapping.action == MAP_CANDIDATE_BACKGROUND
    assert mapping.forced_flow_decision == "advance"
    assert mapping.allow_llm_decision is False

    map_question = decide_next_action(
        PolicyState(
            interviewer_turn_count=1,
            candidate_turn_count=1,
            phase_name="candidate_map",
            gap_competency_id="problem_solving",
        )
    )
    assert map_question.action == ASK_BASELINE
    assert map_question.forced_flow_decision == "advance"
    assert map_question.intent == "establish_context"

    after_map = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="candidate_map",
            gap_competency_id="problem_solving",
        )
    )
    assert after_map.action == ASK_BASELINE
    assert after_map.forced_flow_decision == "advance"
    assert after_map.intent == "establish_context"
    assert after_map.competency_id == "problem_solving"

    still_on_opening = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="opening",
        )
    )
    assert still_on_opening.action == ASK_BASELINE
    assert still_on_opening.forced_flow_decision == "advance"


def test_baseline_alias_canonicalizes_to_establish_context() -> None:
    from products.interviewer.validator import canonical_intent

    assert canonical_intent("baseline") == "establish_context"
    assert canonical_intent("ASK_BASELINE") == "establish_context"
    assert canonical_intent("PROBE_FOR_OWNERSHIP") == "establish_ownership"


def test_progressive_depth_uses_assessment_intent_not_action_name() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=3,
            candidate_turn_count=3,
            phase_name="Problem solving",
            competency_id="problem_solving",
            probe_count=1,
            max_depth=3,
            max_probes=3,
            missing_intents=["establish_context", "establish_ownership"],
        )
    )
    assert decision.intent == "establish_context"
    assert not decision.intent.startswith("PROBE_")

    no_missing = decide_next_action(
        PolicyState(
            interviewer_turn_count=3,
            candidate_turn_count=3,
            phase_name="Problem solving",
            competency_id="problem_solving",
            probe_count=1,
            max_depth=3,
            max_probes=3,
            missing_intents=[],
        )
    )
    assert no_missing.intent == "establish_ownership"
    assert no_missing.action == "PROBE_FOR_OWNERSHIP"


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


def test_non_answer_policy_thresholds_are_honored() -> None:
    clarify = decide_next_action(
        PolicyState(
            interviewer_turn_count=4,
            candidate_turn_count=4,
            phase_name="Problem solving",
            consecutive_unusable=1,
            clarify_after=1,
            change_topic_after=4,
            close_after=6,
        )
    )
    assert clarify.action == CLARIFY_CURRENT_ANSWER
    moved = decide_next_action(
        PolicyState(
            interviewer_turn_count=4,
            candidate_turn_count=4,
            phase_name="Problem solving",
            consecutive_unusable=4,
            clarify_after=1,
            change_topic_after=4,
            close_after=6,
            has_uncovered_competencies=True,
        )
    )
    assert moved.action == MOVE_TO_NEXT_COMPETENCY


def test_repeated_unusable_answers_force_controlled_close() -> None:
    closed = decide_next_action(
        PolicyState(
            interviewer_turn_count=6,
            candidate_turn_count=6,
            phase_name="Problem solving",
            consecutive_unusable=4,
            has_uncovered_competencies=True,
        )
    )
    assert closed.action == CLOSE_INTERVIEW
    assert closed.forced_flow_decision == "close"

