from __future__ import annotations

import pytest

from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import (
    MAP_CANDIDATE_BACKGROUND,
    OPEN_INTERVIEW,
    WALK_RESUME_PROJECT,
    PolicyState,
    decide_next_action,
    outline_from_definition,
)
from products.interviewer.worker import (
    InterviewPlanUnavailableError,
    resolve_live_outline,
)

RESUME = """
Experience
Built the Orion billing reconciler, a Python service matching 4M ledger rows nightly.
Led the Atlas search revamp, replacing the keyword index with embeddings.
"""


def _definition() -> dict:
    return {
        "definition_id": "idef_order_01",
        "time_policy": {"duration_minutes": 30},
        "competencies": [
            {"id": "backend", "name": "Backend engineering", "max_depth": 4, "max_probes": 3},
            {"id": "dsa", "name": "Algorithms", "max_depth": 4, "max_probes": 3},
        ],
    }


def test_outline_order_is_open_then_projects_then_competencies() -> None:
    outline = outline_from_definition(
        _definition(), resume_projects=["Orion billing reconciler", "Atlas search revamp"]
    )
    names = [phase["name"] for phase in outline["phases"]]

    assert names[0] == "opening"
    assert names[1] == "candidate_map"
    project_positions = [i for i, n in enumerate(names) if n.startswith("Resume project:")]
    competency_positions = [
        i for i, phase in enumerate(outline["phases"]) if phase.get("competency_id")
    ]
    assert project_positions, names
    # Every resume project is walked before any JD competency is assessed.
    assert max(project_positions) < min(competency_positions)
    assert names[-1] == "closing"


def test_no_resume_means_no_project_phases() -> None:
    outline = outline_from_definition(_definition(), resume_projects=[])
    names = [phase["name"] for phase in outline["phases"]]
    assert not any(n.startswith("Resume project:") for n in names)
    assert names[:2] == ["opening", "candidate_map"]


def test_flow_builds_project_phases_from_the_resume() -> None:
    flow = InterviewFlow(
        {"phases": []},
        object(),
        interview_definition=_definition(),
        resume_text=RESUME,
    )
    project_phases = [p for p in flow.phases if p.get("project_name")]
    assert project_phases, [p["name"] for p in flow.phases]

    competency_index = min(
        i for i, p in enumerate(flow.phases) if p.get("competency_id")
    )
    last_project_index = max(
        i for i, p in enumerate(flow.phases) if p.get("project_name")
    )
    assert last_project_index < competency_index


def test_interview_opens_before_it_maps_or_probes() -> None:
    fresh = decide_next_action(PolicyState(phase_name="opening"))
    assert fresh.action == OPEN_INTERVIEW
    assert fresh.intent == "opening"

    after_intro = decide_next_action(
        PolicyState(
            phase_name="opening",
            interviewer_turn_count=1,
            candidate_turn_count=1,
        )
    )
    assert after_intro.action == MAP_CANDIDATE_BACKGROUND


def test_project_phase_probes_then_moves_on() -> None:
    state = PolicyState(
        phase_name="Resume project: Orion billing reconciler",
        project_name="Orion billing reconciler",
        interviewer_turn_count=3,
        candidate_turn_count=3,
        probe_count=0,
        max_depth=3,
        max_probes=2,
    )
    first = decide_next_action(state)
    assert first.action == WALK_RESUME_PROJECT
    assert first.competency_id is None
    assert "Orion billing reconciler" in first.reason

    state.probe_count = 2
    done = decide_next_action(state)
    assert done.forced_flow_decision == "advance"


def test_unreachable_context_fails_loudly_instead_of_degrading() -> None:
    # A job carrying a context_id whose context cannot be fetched must NOT fall
    # back to the generic outline: that silently disables policy mode, the
    # evidence ledger and every competency, with no visible error.
    with pytest.raises(InterviewPlanUnavailableError) as excinfo:
        resolve_live_outline(
            interview_definition=None,
            definition_id=None,
            app_env="development",
            context_bound=True,
        )
    assert "interview_context_unreachable" in str(excinfo.value)


def test_local_dev_without_any_context_still_allows_a_generated_plan() -> None:
    outline, source = resolve_live_outline(
        interview_definition=None,
        definition_id=None,
        app_env="development",
        context_bound=False,
    )
    assert outline is None
    assert source == "generated_plan"
