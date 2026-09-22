from __future__ import annotations

import json

from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import (
    MOVE_TO_NEXT_COMPETENCY,
    PolicyState,
    decide_next_action,
)
from products.interviewer.validator import (
    KNOWN_INTENTS,
    parse_generated_question,
    validate_generated_question,
)

DEFAULT_PROBES = [
    "What was your specific responsibility?",
    "What action did you personally take?",
    "How did you decide on that approach?",
    "What was the outcome?",
    "What would you change if you did it again?",
]


def _competency_state(**overrides) -> PolicyState:
    base = dict(
        candidate_turn_count=6,
        interviewer_turn_count=6,
        phase_name="Backend design",
        competency_id="backend_design",
        probe_count=2,
        max_depth=5,
        max_probes=4,
    )
    base.update(overrides)
    return PolicyState(**base)


def test_policy_never_emits_action_name_as_intent() -> None:
    for probe_count in range(0, 6):
        decision = decide_next_action(_competency_state(probe_count=probe_count))
        assert decision.intent == decision.intent.lower()
        assert not decision.intent.startswith("PROBE_")
        assert decision.intent in KNOWN_INTENTS


def test_deep_technical_followup_passes_validation() -> None:
    generated = parse_generated_question(
        json.dumps(
            {
                "question": "How did you keep the ingestion queue from backing up at peak load?",
                "competency_id": "backend_design",
                "intent": "applied_understanding",
                "depth": 3,
            }
        )
    )
    result = validate_generated_question(
        generated,
        definition=None,
        policy_competency_id="backend_design",
        policy_intent="problem_or_complexity",
        policy_depth=3,
        max_depth=4,
        recent_questions=[],
        allowed_probes=DEFAULT_PROBES,
        job_description="Backend engineer building high-throughput data APIs.",
        resume_text="Built ingestion services in Python.",
        recent_turns=["We moved ingestion onto a worker pool."],
    )
    assert result.ok is True, result.reasons


def test_policy_intent_is_not_second_guessed_by_probe_list() -> None:
    # establish_context and problem_or_complexity used to be rejected outright
    # because their alias words are absent from the default probe sentences.
    for intent in ("establish_context", "problem_or_complexity", "rephrase"):
        result = validate_generated_question(
            parse_generated_question(
                json.dumps({"question": "What did you change first?", "depth": 1})
            ),
            definition=None,
            policy_competency_id=None,
            policy_intent=intent,
            policy_depth=1,
            max_depth=4,
            recent_questions=[],
            allowed_probes=DEFAULT_PROBES,
        )
        assert result.ok is True, (intent, result.reasons)


def test_leading_questions_are_rejected() -> None:
    for question in (
        "You used a message queue there, right?",
        "So you chose Postgres for that workload?",
        "You shipped it on time, didn't you?",
    ):
        result = validate_generated_question(
            parse_generated_question(json.dumps({"question": question, "depth": 2})),
            definition=None,
            policy_competency_id=None,
            policy_intent="applied_understanding",
            policy_depth=2,
            max_depth=4,
            recent_questions=[],
            allowed_probes=[],
            job_description="Backend engineer working on database and queue systems.",
        )
        assert "leading_question" in result.reasons, question


def test_no_gain_stop_rule_transitions_off_a_dead_seam() -> None:
    still_producing = decide_next_action(
        _competency_state(probes_without_gain=1, has_uncovered_competencies=True)
    )
    assert still_producing.forced_flow_decision == "probe"

    exhausted = decide_next_action(
        _competency_state(probes_without_gain=2, has_uncovered_competencies=True)
    )
    assert exhausted.action == MOVE_TO_NEXT_COMPETENCY
    assert exhausted.forced_flow_decision == "advance"
    assert exhausted.reason == "probes stopped yielding new evidence"


def test_fallback_never_repeats_an_already_asked_question() -> None:
    definition = {
        "definition_id": "idef_fallback_01",
        "competencies": [
            {"id": "c1", "name": "Data modelling", "max_depth": 4, "max_probes": 3}
        ],
        "question_ladders": [
            {
                "competency_id": "c1",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "example_question": "Describe a data model you designed.",
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "example_question": "Which part did you own?",
                    },
                ],
            }
        ],
    }
    flow = InterviewFlow({"phases": []}, object(), interview_definition=definition)
    policy = PolicyState(competency_id="c1")
    decision = decide_next_action(policy)
    decision.competency_id = "c1"
    decision.intent = "establish_context"

    spoken: list[str] = []
    for _ in range(4):
        question = flow._fallback_spoken_question(decision)
        assert question not in spoken, f"fallback repeated: {question!r}"
        spoken.append(question)
        flow.interviewer_turns.append(question)
