"""P4: replay fixtures and human rubric on 20 recorded sessions."""
from __future__ import annotations

import pytest

from products.interviewer.coverage import required_intents_for
from products.interviewer.replay import (
    RUBRIC_CRITERIA,
    recorded_sessions,
    replay_definition,
    run_replay,
    score_followup_rubric,
)

SESSIONS = recorded_sessions()
SCENARIOS = {
    "thin_answer",
    "ownership_dodge",
    "metric_named",
    "contradiction",
    "time_up",
}


def test_replay_catalog_has_twenty_named_sessions() -> None:
    assert len(SESSIONS) == 20
    assert {item.fixture_id for item in SESSIONS} == {
        item.fixture_id for item in SESSIONS
    }
    present = {item.scenario for item in SESSIONS}
    assert present == SCENARIOS
    for scenario in SCENARIOS:
        assert sum(1 for item in SESSIONS if item.scenario == scenario) == 4


def test_junior_replay_keeps_the_published_intent_bar() -> None:
    junior = next(item for item in SESSIONS if item.job_target_level == "junior")
    definition = replay_definition()
    required = required_intents_for(definition, junior.competency_id)
    assert "establish_ownership" in required
    assert "applied_understanding" in required
    result = run_replay(junior)
    assert result.decision.intent == "establish_ownership"
    assert "establish_ownership" in result.missing_after


@pytest.mark.parametrize("session", SESSIONS, ids=lambda item: item.fixture_id)
def test_replay_next_intent_matches_missing_evidenced_intent(session) -> None:
    result = run_replay(session)
    assert result.decision.action == session.expected_action
    assert result.decision.intent == session.expected_intent
    if result.decision.competency_id:
        assert result.decision.competency_id in result.published_ids
        assert result.decision.competency_id != "system_design"
    if not session.allow_competency_change:
        assert result.decision.competency_id in {
            session.expected_competency_id,
            None,
        }
    for intent in session.must_not_cover:
        assert intent not in result.covered_after
    if (
        result.decision.action
        not in {
            "CLARIFY_CURRENT_ANSWER",
            "MOVE_TO_NEXT_COMPETENCY",
            "OFFER_FINAL_ADDITION",
            "CLOSE_INTERVIEW",
            "CHECK_REMAINING_GAP",
        }
        and result.missing_after
    ):
        assert result.decision.intent == result.missing_after[0]


@pytest.mark.parametrize("session", SESSIONS, ids=lambda item: item.fixture_id)
def test_recorded_session_passes_human_rubric(session) -> None:
    verdict = score_followup_rubric(run_replay(session))
    assert set(verdict.checks) == set(RUBRIC_CRITERIA)
    assert verdict.passed, verdict.notes


def test_all_twenty_recorded_sessions_pass_the_human_rubric() -> None:
    failed = []
    for session in SESSIONS:
        verdict = score_followup_rubric(run_replay(session))
        if not verdict.passed:
            failed.append((session.fixture_id, verdict.notes))
    assert failed == []
