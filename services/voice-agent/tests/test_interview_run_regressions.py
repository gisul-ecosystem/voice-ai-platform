from __future__ import annotations

import json

import pytest

from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import (
    CLOSE_INTERVIEW,
    OFFER_FINAL_ADDITION,
    PolicyState,
    decide_next_action,
)


def _definition() -> dict:
    return {
        "definition_id": "idef_regress",
        "prompt_version": "interviewer-system-v2",
        "competencies": [
            {
                "id": "flink",
                "name": "Apache Flink",
                "importance": "high",
                "definition": "Builds stateful stream processing jobs.",
                "evidence_expected": ["approach", "mechanism"],
                "max_depth": 5,
                "max_probes": 4,
            }
        ],
    }


class RepeatingLlm:
    """Always returns the same question, so the validator always rejects it."""

    def __init__(self, question: str) -> None:
        self.question = question

    async def generate_reply(self, messages, **_kwargs) -> str:
        return json.dumps(
            {
                "question": self.question,
                "competency_id": "flink",
                "intent": "applied_understanding",
                "depth": 2,
                "answer_evaluation": {
                    "technical_substance": "deep",
                    "key_facts_stated": ["9k events per second"],
                    "reasoning": "Gave the mechanism and a measured figure.",
                    "matches_evidence_expected": True,
                    "needs_clarification": False,
                    "factually_correct": True,
                    "slots_demonstrated": ["ownership"],
                    "slots_claimed": [],
                    "contradicts_earlier": False,
                },
            }
        )


@pytest.mark.asyncio
async def test_rejected_question_keeps_the_answer_verdict() -> None:
    repeated = "What exactly did you change in that job?"
    llm = RepeatingLlm(repeated)
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        job_description="Streaming engineer working on Flink pipelines.",
        # Pre-seed the question so the model's output is a duplicate.
        interviewer_turns=["q1", repeated],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )

    await flow.generate_next_question("I owned that operator and tuned its state backend.")

    # The question was rejected, but the verdict about the ANSWER must survive:
    # dropping it stalls the evidence ledger for the rest of the interview.
    assert flow.last_validator_ok is False
    assert flow.last_answer_evaluation is not None
    assert flow.last_answer_evaluation["slots_demonstrated"] == ["ownership"]
    assert flow.evidence_ledger["flink"].status_of("ownership") == "demonstrated"


def _closing_state(**overrides) -> PolicyState:
    base = dict(
        phase_name="closing",
        candidate_turn_count=12,
        interviewer_turn_count=12,
        competency_id="flink",
        elapsed_seconds=60,
        soft_end_seconds=27 * 60,
        target_end_seconds=30 * 60,
        hard_end_seconds=35 * 60,
    )
    base.update(overrides)
    return PolicyState(**base)


def test_final_addition_is_offered_once_then_closes() -> None:
    first = decide_next_action(_closing_state(final_addition_offered=False))
    assert first.action == OFFER_FINAL_ADDITION

    second = decide_next_action(_closing_state(final_addition_offered=True))
    assert second.action == CLOSE_INTERVIEW
    assert second.reason == "final addition already offered"


def test_flow_marks_final_addition_as_offered() -> None:
    flow = InterviewFlow({"phases": []}, object(), interview_definition=_definition())
    assert flow.final_addition_offered is False

    class _Decision:
        intent = "final_addition"
        competency_id = None

    flow._remember_generated(
        type("G", (), {"competency_id": None, "intent": "final_addition", "depth": 1,
                       "source_claim_ids": [], "probe_shape": None})(),
        _Decision(),
    )
    assert flow.final_addition_offered is True
