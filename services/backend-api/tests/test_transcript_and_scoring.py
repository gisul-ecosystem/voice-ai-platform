"""Production tests for transcript completeness and scorecard generation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from brain.scoring import build_scorecard_bundle, build_transcript_document
from brain.scoring_service import generate_and_store_scorecard, get_full_transcript
from db import definitions, interviews, mongo, scorecards
from models.brain import InterviewDefinitionVersion, JobIntelligence, JobRoleSummary
from models.schemas import InterviewSetupConfig
from brain.compiler import compile_blueprint
from brain.publish import publish_definition


@pytest.fixture(autouse=True)
def _memory_mongo(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "")
    mongo.set_fallback_mode(True)
    yield
    mongo.set_fallback_mode(False)


def _setup() -> InterviewSetupConfig:
    return InterviewSetupConfig(
        title="Backend interview",
        role="Backend Engineer",
        seniority="mid",
        difficulty="applied",
        durationMinutes=30,
        language="English",
        competencies=["Problem solving", "Ownership"],
        maxProbesPerPhase=2,
        monitoringEnabled=True,
        recordingEnabled=False,
    )


async def _published_definition() -> InterviewDefinitionVersion:
    job = JobIntelligence(
        role=JobRoleSummary(title="Backend Engineer", target_level="mid"),
        raw_job_description="Build APIs, own incidents, communicate clearly.",
        approved=True,
        approved_at=datetime.now(timezone.utc),
    )
    draft = compile_blueprint(
        job_intelligence=job,
        creator_competencies=["Problem solving", "Ownership"],
        include_scenarios=False,
    )
    published = publish_definition(draft, published_by="tester@example.com")
    await definitions.save_definition(published)
    return published


def test_transcript_document_orders_all_spoken_turns() -> None:
    doc = build_transcript_document(
        session_id="ses_transcript_01",
        turns=[
            {
                "turn_id": "t2",
                "speaker": "candidate",
                "text": "I built billing retries.",
                "sequence_number": 2,
            },
            {
                "turn_id": "t1",
                "speaker": "agent",
                "text": "Please introduce yourself.",
                "sequence_number": 1,
            },
            {
                "turn_id": "t3",
                "speaker": "agent",
                "text": "Sorry, I did not catch that.",
                "sequence_number": 3,
            },
        ],
    )
    assert doc["turn_count"] == 3
    assert doc["agent_turn_count"] == 2
    assert doc["candidate_turn_count"] == 1
    assert [item["turn_id"] for item in doc["turns"]] == ["t1", "t2", "t3"]


def test_scorecard_requires_evidence_citations() -> None:
    definition = {
        "definition_id": "idef_score_test_01",
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "evidence_expected": ["context", "action", "result"],
                "rubric": [
                    {"rating": 1, "description": "No evidence"},
                    {"rating": 3, "description": "Explains problem action result"},
                    {"rating": 5, "description": "Strong tradeoffs and impact"},
                ],
            }
        ],
    }
    scorecard, evidence = build_scorecard_bundle(
        session_id="ses_score_test_01",
        definition=definition,
        questions=[
            {
                "question_id": "q1",
                "competency_id": "problem_solving",
                "text": "What problem did you solve?",
            }
        ],
        answers=[
            {
                "answer_id": "a1",
                "question_id": "q1",
                "turn_ids": ["turn_candidate_1"],
                "usable": True,
                "final_transcript": (
                    "I owned the billing timeout context. I implemented retries "
                    "and the result was lower latency for checkout."
                ),
            }
        ],
    )
    assert evidence
    assert all(item.turn_ids for item in evidence)
    scored = scorecard.competencies[0]
    assert scored.outcome == "scored"
    assert scored.rating is not None
    assert scored.evidence_ids
    assert scored.review_required is True
    assert scorecard.human_review_status == "pending"


def test_missing_answers_are_not_assessed() -> None:
    definition = {
        "definition_id": "idef_score_test_02",
        "competencies": [
            {
                "id": "communication",
                "name": "Communication",
                "evidence_expected": ["clarity"],
                "rubric": [
                    {"rating": 1, "description": "Weak"},
                    {"rating": 3, "description": "Clear"},
                    {"rating": 5, "description": "Excellent"},
                ],
            }
        ],
    }
    scorecard, evidence = build_scorecard_bundle(
        session_id="ses_score_test_02",
        definition=definition,
        questions=[],
        answers=[],
    )
    assert evidence == []
    assert scorecard.competencies[0].outcome == "not_assessed"
    assert scorecard.competencies[0].rating is None
    assert scorecard.overall_recommendation == "insufficient_evidence"


@pytest.mark.asyncio
async def test_completed_session_persists_transcript_and_scorecard() -> None:
    published = await _published_definition()
    context = await interviews.create_context(
        "Build APIs and own production systems.",
        "Built billing retries and owned on-call.",
        _setup().model_dump(mode="python"),
        definition_id=published.definition_id,
    )
    session_id = await interviews.create_live_session(
        product_id="interviewer",
        context_id=context["context_id"],
        candidate_id="candidate_test",
        room="room-test",
        correlation_id="corr-test",
        expires_at=datetime.now(timezone.utc),
    )
    await interviews.append_turn(
        session_id,
        {
            "turn_id": "turn_agent_1",
            "speaker": "agent",
            "text": "Please introduce yourself and relevant work.",
            "phase_index": 0,
            "sequence_number": 1,
            "is_final": True,
        },
    )
    await interviews.append_turn(
        session_id,
        {
            "turn_id": "turn_candidate_1",
            "speaker": "candidate",
            "text": (
                "I owned billing API timeouts. I implemented retries and the "
                "result was lower checkout latency."
            ),
            "phase_index": 0,
            "sequence_number": 2,
            "is_final": True,
        },
    )
    await interviews.append_turn(
        session_id,
        {
            "turn_id": "turn_agent_2",
            "speaker": "agent",
            "text": "What was difficult about that ownership?",
            "phase_index": 1,
            "sequence_number": 3,
            "is_final": True,
        },
    )
    await interviews.append_turn(
        session_id,
        {
            "turn_id": "turn_candidate_2",
            "speaker": "candidate",
            "text": (
                "The hard part was choosing between queue retries and HTTP "
                "client retries because of duplicate charges."
            ),
            "phase_index": 1,
            "sequence_number": 4,
            "is_final": True,
        },
    )

    transcript = await get_full_transcript(session_id)
    assert transcript is not None
    assert transcript["turn_count"] == 4
    assert transcript["candidate_turn_count"] == 2
    assert transcript["agent_turn_count"] == 2

    await interviews.transition_session(
        session_id,
        expected=("joining", "live", "completing"),
        status="completed",
        reason="test_complete",
    )
    result = await generate_and_store_scorecard(session_id)
    assert result is not None
    assert result["session_id"] == session_id
    assert result["definition_id"] == published.definition_id
    assert result["competencies"]
    assert result["human_review_status"] == "pending"
    stored = await scorecards.get_scorecard(session_id)
    assert stored is not None
    # Immutable: second generate returns same scorecard.
    again = await generate_and_store_scorecard(session_id)
    assert again is not None
    assert again["created_at"] == result["created_at"]
