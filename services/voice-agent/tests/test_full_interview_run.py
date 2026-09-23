"""Whole-interview regression test.

Unit tests verify single turns. The bugs that reached production lived between
turns: a verdict dropped at a handoff stalled the evidence ledger for an entire
interview, and the closing state repeated forever. This drives a complete
interview and asserts on the end state, which is the only place those show up.
"""
from __future__ import annotations

import json

import pytest

from products.interviewer.evidence import SLOT_KEYS
from products.interviewer.flow import InterviewFlow

# Wrapped description lines, like a real CV export - not tidy one-liners.
RESUME = """
Abhijeet Singh

Experience
Built the Orion billing reconciler, a Python service matching 4M ledger rows nightly
against Stripe payouts, cutting manual reconciliation from 6 hours to 20 minutes.
Led the Atlas search revamp, replacing the Postgres keyword index with pgvector
embeddings and reducing p95 search latency from 900ms to 180ms.

Skills
Python, PostgreSQL, Kafka, Airflow
"""

JOB_DESCRIPTION = (
    "Senior backend engineer. Owns data reconciliation services and search "
    "infrastructure. Requires Python, PostgreSQL, and distributed systems."
)


def _definition() -> dict:
    return {
        "definition_id": "idef_full_run",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {"duration_minutes": 30},
        "competencies": [
            {
                "id": "reconciliation",
                "name": "Data reconciliation",
                "importance": "high",
                "definition": "Builds correct, auditable reconciliation pipelines.",
                "evidence_expected": ["approach", "mechanism"],
                "max_depth": 5,
                "max_probes": 4,
                "weight": 50.0,
            },
            {
                "id": "search",
                "name": "Search infrastructure",
                "importance": "high",
                "definition": "Designs and tunes retrieval systems.",
                "evidence_expected": ["approach", "cost"],
                "max_depth": 5,
                "max_probes": 4,
                "weight": 30.0,
            },
            {
                "id": "schema",
                "name": "Schema design",
                "importance": "medium",
                "definition": "Evolves schemas safely.",
                "evidence_expected": ["approach"],
                "max_depth": 4,
                "max_probes": 3,
                "weight": 20.0,
            },
        ],
    }


class CooperativeCandidate:
    """Always demonstrates whichever evidence slot the prompt is targeting.

    A perfect candidate is the strict case: if the ledger does not fill here,
    it cannot fill for a real one.
    """

    TARGET_MARKER = "YOUR TARGET THIS TURN: "

    # Varied phrasings so the near-duplicate rule is not what is under test.
    PHRASINGS = (
        "Walk me through how {slot} worked on the reconciler.",
        "What decided {slot} when you rebuilt the search index?",
        "On the ledger matcher, which part of {slot} was yours?",
        "Why did {slot} end up that way instead of the alternative?",
        "Where does {slot} break once volume triples?",
        "What number moved when you changed {slot}?",
        "Talk me through {slot} on the payouts job.",
        "If {slot} had to halve in cost, what would you give up?",
    )

    def __init__(self) -> None:
        self.turn = 0
        self.questions: list[str] = []

    def _target(self, system_prompt: str) -> str:
        if self.TARGET_MARKER not in system_prompt:
            return ""
        value = system_prompt.split(self.TARGET_MARKER, 1)[1].split("\n", 1)[0].strip()
        return value if value in SLOT_KEYS else ""

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.turn += 1
        target = self._target(messages[0]["content"])
        template = self.PHRASINGS[self.turn % len(self.PHRASINGS)]
        question = f"{template.format(slot=(target or 'that design').replace('_', ' '))} [{self.turn}]"
        self.questions.append(question)
        return json.dumps(
            {
                "question": question,
                "competency_id": "",
                "intent": "applied_understanding",
                "depth": 2,
                "answer_evaluation": {
                    "technical_substance": "deep",
                    "key_facts_stated": [f"fact {self.turn}"],
                    "reasoning": "Specific mechanism and figures given.",
                    "matches_evidence_expected": True,
                    "needs_clarification": False,
                    "factually_correct": True,
                    "slots_demonstrated": [target] if target else [],
                    "slots_claimed": [],
                    "contradicts_earlier": False,
                },
            }
        )


async def _run_interview(flow: InterviewFlow, max_turns: int = 40) -> list[str]:
    """Drive the interview to completion, returning the sections visited in order."""
    await flow.generate_next_question(None)
    visited: list[str] = []
    for _ in range(max_turns):
        if flow.completed:
            break
        await flow.generate_next_question(
            "I owned that piece and rewrote it; throughput went from 2k to 9k rows per second."
        )
        name = str(flow.current_phase().get("name"))
        if not visited or visited[-1] != name:
            visited.append(name)
    return visited


@pytest.fixture
def flow() -> InterviewFlow:
    return InterviewFlow(
        {"phases": []},
        CooperativeCandidate(),
        interview_definition=_definition(),
        job_description=JOB_DESCRIPTION,
        resume_text=RESUME,
        difficulty="applied",
    )


@pytest.mark.asyncio
async def test_interview_reaches_every_competency(flow: InterviewFlow) -> None:
    visited = await _run_interview(flow)
    for competency in _definition()["competencies"]:
        assert any(competency["name"] in section for section in visited), (
            f"{competency['name']} was never asked about",
            visited,
        )


@pytest.mark.asyncio
async def test_evidence_ledger_actually_fills(flow: InterviewFlow) -> None:
    await _run_interview(flow)
    for competency_id, entry in flow.evidence_ledger.items():
        # A verdict dropped at any handoff shows up here as a flat zero.
        assert entry.demonstrated_count() > 0, (
            f"no evidence recorded for {competency_id}",
            entry.states,
        )


@pytest.mark.asyncio
async def test_interview_closes_instead_of_looping(flow: InterviewFlow) -> None:
    await _run_interview(flow)
    assert flow.completed is True, "interview never reached a close"


@pytest.mark.asyncio
async def test_no_question_is_asked_twice(flow: InterviewFlow) -> None:
    await _run_interview(flow)
    asked = [q.strip().lower() for q in flow.interviewer_turns if q.strip()]
    assert len(asked) == len(set(asked)), "a question was repeated"


@pytest.mark.asyncio
async def test_resume_projects_are_walked_before_competencies(flow: InterviewFlow) -> None:
    project_indexes = [i for i, p in enumerate(flow.phases) if p.get("project_name")]
    competency_indexes = [i for i, p in enumerate(flow.phases) if p.get("competency_id")]
    assert project_indexes, [p["name"] for p in flow.phases]
    assert max(project_indexes) < min(competency_indexes)


def test_wrapped_resume_lines_do_not_become_separate_projects(flow: InterviewFlow) -> None:
    names = [p["project_name"] for p in flow.phases if p.get("project_name")]
    # "against Stripe payouts, ..." is a wrapped continuation, not a project.
    assert not any(name[:1].islower() for name in names), names


def test_weighting_controls_interview_time(flow: InterviewFlow) -> None:
    minutes = {
        p["competency_id"]: p["duration_minutes"]
        for p in flow.phases
        if p.get("competency_id")
    }
    assert minutes["reconciliation"] > minutes["search"] > minutes["schema"]
