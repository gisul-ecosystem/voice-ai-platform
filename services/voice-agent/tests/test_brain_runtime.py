from __future__ import annotations

from products.interviewer.brain_runtime import (
    brain_bundle_to_initial_state,
    definition_id_for_session,
    flow_to_brain_state,
)


class FakeFlow:
    def __init__(self) -> None:
        self.candidate_turns = ["I built a payments service."]
        self.probe_count = 2
        self.completed = False
        self.consecutive_unusable = 0
        self.last_question_depth = 2

    def current_phase(self) -> dict:
        return {"competency_id": "problem_solving"}


def test_definition_id_is_session_scoped() -> None:
    first = definition_id_for_session("ses_aaaaaaaaaaaaaaaa")
    second = definition_id_for_session("ses_bbbbbbbbbbbbbbbb")
    assert first != second
    assert first.startswith("idef_")


def test_definition_id_prefers_explicit_published_id() -> None:
    resolved = definition_id_for_session(
        "ses_aaaaaaaaaaaaaaaa",
        "ctx_bbbbbbbbbbbbbbbb",
        explicit_definition_id="idef_published_real_01",
    )
    assert resolved == "idef_published_real_01"


def test_brain_bundle_restore_prefers_questions_and_answers() -> None:
    restored = brain_bundle_to_initial_state(
        {
            "state": {
                "session_id": "ses_test01",
                "state_version": 4,
                "current_depth": 3,
                "active_question_id": "q_abc",
            },
            "questions": [
                {"question_id": "q_abc", "text": "What did you build?"},
            ],
            "answers": [
                {
                    "question_id": "q_abc",
                    "final_transcript": "I built a billing API.",
                }
            ],
        }
    )
    assert restored["interviewer_turns"] == ["What did you build?"]
    assert restored["candidate_turns"] == ["I built a billing API."]
    assert restored["brain_state_version"] == 4
    assert restored["brain_active_question_id"] == "q_abc"
    assert restored["initial_probe_count"] == 2


def test_brain_bundle_empty_returns_empty() -> None:
    assert brain_bundle_to_initial_state(None) == {}
    assert brain_bundle_to_initial_state({}) == {}


def test_flow_to_brain_state_is_session_isolated() -> None:
    payload = flow_to_brain_state(
        session_id="ses_alpha01",
        definition_id="idef_pending_alpha01",
        flow=FakeFlow(),
        state_version=2,
        active_question_id="q_1",
        asked_question_ids=["q_1"],
        started_monotonic=0,
    )
    assert payload["session_id"] == "ses_alpha01"
    assert payload["state_version"] == 2
    assert payload["active_question_id"] == "q_1"
    assert payload["coverage"] == {}
    assert payload["consecutive_unusable_answers"] == 0
