"""Tests for Milestone 4 policy engine."""
from __future__ import annotations

from products.interviewer.policy import (
    ASK_BASELINE,
    CLARIFY_CURRENT_ANSWER,
    CLOSE_INTERVIEW,
    MAP_CANDIDATE_BACKGROUND,
    MOVE_TO_NEXT_COMPETENCY,
    OPEN_INTERVIEW,
    PROBE_FOR_REFLECTION,
    PROBE_FOR_RESULT,
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
    assert names[2] == "resume projects"
    assert "Problem solving" in names
    assert names.index("resume projects") < names.index("Problem solving")
    assert names[-1] == "closing"


def test_outline_skips_jd_duty_fragment_competencies() -> None:
    outline = outline_from_definition(
        {
            "time_policy": {"duration_minutes": 30},
            "competencies": [
                {"id": "design", "name": "Design", "evidence_expected": []},
                {"id": "develop", "name": "develop", "evidence_expected": []},
                {
                    "id": "maintain",
                    "name": "and maintain applications using Python.",
                    "evidence_expected": [],
                },
                {
                    "id": "python",
                    "name": "Python backend",
                    "evidence_expected": ["apis"],
                },
                {
                    "id": "debug",
                    "name": "Debugging",
                    "evidence_expected": ["incidents"],
                },
            ],
        }
    )
    assert outline is not None
    names = [phase["name"] for phase in outline["phases"]]
    assert "Design" not in names
    assert "develop" not in names
    assert "and maintain applications using Python." not in names
    assert "Python backend" in names
    assert "Debugging" in names
    assert names[0] == "opening"
    assert names[1] == "candidate_map"
    assert names[2] == "resume projects"
    assert names[-1] == "closing"


def test_outline_caps_competencies_on_short_interviews() -> None:
    comps = [
        {"id": f"c{i}", "name": f"Skill {i}", "evidence_expected": ["x"]}
        for i in range(1, 7)
    ]
    outline = outline_from_definition(
        {"time_policy": {"duration_minutes": 15}, "competencies": comps}
    )
    assert outline is not None
    skip = {"opening", "candidate_map", "resume projects", "closing"}
    competency_phases = [p for p in outline["phases"] if p["name"] not in skip]
    assert len(competency_phases) == 3


def test_first_explicit_unknown_clarifies_same_topic() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=4,
            candidate_turn_count=4,
            phase_name="Python Proficiency",
            competency_id="python",
            last_answer_usability="explicit_unknown",
            consecutive_explicit_unknown=1,
            has_uncovered_competencies=True,
        )
    )
    assert decision.action == CLARIFY_CURRENT_ANSWER
    assert decision.forced_flow_decision == "probe"


def test_second_explicit_unknown_advances() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=5,
            candidate_turn_count=5,
            phase_name="Python Proficiency",
            competency_id="python",
            last_answer_usability="explicit_unknown",
            consecutive_explicit_unknown=2,
            has_uncovered_competencies=True,
        )
    )
    assert decision.action == MOVE_TO_NEXT_COMPETENCY


def test_substantive_covered_answer_advances_without_extra_probe() -> None:
    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=5,
            candidate_turn_count=5,
            phase_name="Python Proficiency",
            competency_id="python",
            probe_count=2,
            max_probes=4,
            missing_intents=[],
            coverage_complete=True,
            last_answer_usability="usable",
            last_answer_quality="sufficient",
            usable_exchanges_on_competency=1,
            has_uncovered_competencies=True,
            elapsed_seconds=600,
            target_end_seconds=1800,
        )
    )
    assert decision.action == MOVE_TO_NEXT_COMPETENCY
    assert "substantive" in decision.reason or "covered" in decision.reason


def test_early_offer_final_is_blocked_before_min_length() -> None:
    from products.interviewer.policy import OFFER_FINAL_ADDITION

    decision = decide_next_action(
        PolicyState(
            interviewer_turn_count=6,
            candidate_turn_count=6,
            phase_name="closing",
            elapsed_seconds=300,
            soft_end_seconds=200,
            target_end_seconds=1800,
            min_elapsed_before_close_seconds=720,
            min_candidate_turns_before_close=8,
            at_last_competency=True,
        )
    )
    assert decision.action != OFFER_FINAL_ADDITION
    assert decision.action != CLOSE_INTERVIEW
    assert decision.action in {PROBE_FOR_REFLECTION, PROBE_FOR_RESULT}
    assert decision.forced_flow_decision == "probe"


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
    assert map_question.action == MAP_CANDIDATE_BACKGROUND
    assert map_question.forced_flow_decision == "advance"
    assert map_question.intent == "resume_project"
    assert map_question.section == "resume_projects"

    after_map = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="candidate_map",
            gap_competency_id="problem_solving",
        )
    )
    assert after_map.action == MAP_CANDIDATE_BACKGROUND
    assert after_map.forced_flow_decision == "advance"
    assert after_map.intent == "resume_project"
    assert after_map.competency_id is None

    still_on_opening = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="opening",
        )
    )
    assert still_on_opening.action == MAP_CANDIDATE_BACKGROUND
    assert still_on_opening.forced_flow_decision == "advance"
    assert still_on_opening.section == "resume_projects"


def test_resume_projects_probes_before_competency() -> None:
    first = decide_next_action(
        PolicyState(
            interviewer_turn_count=2,
            candidate_turn_count=2,
            phase_name="resume projects",
            probe_count=0,
            max_probes=3,
            max_depth=3,
            gap_competency_id="problem_solving",
        )
    )
    assert first.action == ASK_BASELINE
    assert first.forced_flow_decision == "probe"
    assert first.section == "resume_projects"
    assert first.competency_id is None

    ownership = decide_next_action(
        PolicyState(
            interviewer_turn_count=3,
            candidate_turn_count=3,
            phase_name="resume projects",
            probe_count=1,
            max_probes=3,
            max_depth=3,
        )
    )
    assert ownership.action == "PROBE_FOR_OWNERSHIP"
    assert ownership.forced_flow_decision == "probe"

    done = decide_next_action(
        PolicyState(
            interviewer_turn_count=5,
            candidate_turn_count=5,
            phase_name="resume projects",
            probe_count=3,
            max_probes=3,
            max_depth=3,
            gap_competency_id="problem_solving",
            usable_exchanges_on_competency=1,
        )
    )
    assert done.forced_flow_decision == "advance"
    assert done.intent == "establish_context"


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
    assert baseline.action == MAP_CANDIDATE_BACKGROUND
    assert baseline.forced_flow_decision == "advance"
    assert baseline.section == "resume_projects"

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
    # Min length satisfied — repeated unusable may close.
    closed = decide_next_action(
        PolicyState(
            interviewer_turn_count=10,
            candidate_turn_count=10,
            phase_name="Problem solving",
            consecutive_unusable=4,
            has_uncovered_competencies=False,
            elapsed_seconds=900,
            target_end_seconds=1800,
            min_elapsed_before_close_seconds=720,
            min_candidate_turns_before_close=8,
        )
    )
    assert closed.action == CLOSE_INTERVIEW
    assert closed.forced_flow_decision == "close"

    # Too early: advance remaining topics instead of closing.
    early = decide_next_action(
        PolicyState(
            interviewer_turn_count=4,
            candidate_turn_count=4,
            phase_name="Problem solving",
            consecutive_unusable=4,
            has_uncovered_competencies=True,
            elapsed_seconds=120,
            target_end_seconds=1800,
            min_elapsed_before_close_seconds=720,
            min_candidate_turns_before_close=8,
        )
    )
    assert early.action == MOVE_TO_NEXT_COMPETENCY

