"""Phase 4 quality harness: fixtures, metrics, red-team, replay fields."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from brain.compiler import compile_blueprint
from brain.extractors import extract_candidate_profile, extract_job_intelligence
from brain.quality import compute_quality_metrics
from brain.scoring import build_scorecard_bundle
from models.brain import JobRoleSummary
from tests.testdata.quality_fixtures import (
    ENGINEERING_JD,
    ENGINEERING_RESUME,
    INJECTION_JD,
    SALES_JD,
    SALES_RESUME,
)


def _approved(job_text: str, title: str, level: str = "mid"):
    extracted = extract_job_intelligence(job_text)
    return extracted.model_copy(
        update={
            "approved": True,
            "approved_at": datetime.now(timezone.utc),
            "role": JobRoleSummary(title=title, target_level=level),  # type: ignore[arg-type]
        }
    )


def test_golden_sales_and_engineering_compile_domain_neutral() -> None:
    sales = compile_blueprint(
        job_intelligence=_approved(SALES_JD, "Enterprise Sales Executive"),
        creator_competencies=["Discovery", "Negotiation"],
        include_scenarios=False,
    )
    eng = compile_blueprint(
        job_intelligence=_approved(ENGINEERING_JD, "Senior Backend Engineer", "senior"),
        creator_competencies=["Python", "Ownership"],
        include_scenarios=False,
    )
    assert sales.prompt_version == eng.prompt_version
    sales_names = {item.name.lower() for item in sales.competencies}
    eng_names = {item.name.lower() for item in eng.competencies}
    assert "discovery" in sales_names
    assert "python" in eng_names
    sales_resume = extract_candidate_profile(SALES_RESUME)
    eng_resume = extract_candidate_profile(ENGINEERING_RESUME)
    assert sales_resume.projects
    assert eng_resume.projects


def test_quality_metrics_contain_counts_not_transcript_text() -> None:
    metrics = compute_quality_metrics(
        questions=[
            {"text": "What part of that deal did you personally handle?"},
            {"text": "What part of that deal did you personally handle?"},
            {"text": "What was the outcome?"},
        ],
        answers=[{"final_transcript": "I closed the deal after discovery."}],
        coverage={
            "negotiation": {"status": "complete"},
            "discovery": {"status": "partial"},
        },
        competency_outcomes=["scored", "not_assessed"],
        validator_results=[True, False, True],
    )
    payload = metrics.model_dump()
    assert payload["repeated_question_rate"] > 0
    assert payload["mandatory_coverage_pct"] == 50.0
    assert payload["not_assessed_rate"] == 0.5
    assert payload["validator_failure_rate"] == pytest.approx(1 / 3, rel=0.01)
    joined = " ".join(str(value) for value in payload.values())
    assert "deal" not in joined
    assert "discovery" not in joined


def test_injection_in_jd_cannot_create_prohibited_competency() -> None:
    draft = compile_blueprint(
        job_intelligence=_approved(INJECTION_JD, "Sales Executive"),
        include_scenarios=False,
    )
    blob = " ".join(item.name.lower() for item in draft.competencies)
    assert "religion" not in blob
    assert "age" not in blob


def test_scorecard_excerpts_and_missing_intents_are_evidence_linked() -> None:
    definition = {
        "definition_id": "idef_quality_01",
        "competencies": [
            {
                "id": "negotiation",
                "name": "Negotiation",
                "importance": "high",
                "weight": 100,
                "evidence_expected": ["context", "result"],
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "rubric": [
                    {"rating": 1, "description": "No evidence"},
                    {"rating": 3, "description": "Describes a relevant example"},
                    {"rating": 5, "description": "Strong tradeoffs"},
                ],
            }
        ],
    }
    scorecard, evidence = build_scorecard_bundle(
        session_id="ses_quality_01",
        definition=definition,
        questions=[
            {
                "question_id": "q1",
                "competency_id": "negotiation",
                "intent": "establish_context",
                "prompt_version": "interviewer-system-v2",
                "policy_action": "PROBE_FOR_CONTEXT",
                "validator_ok": True,
                "text": "Can you briefly describe the situation?",
            }
        ],
        answers=[
            {
                "answer_id": "a1",
                "question_id": "q1",
                "turn_ids": ["turn_1"],
                "usable": True,
                "final_transcript": (
                    "In that enterprise deal context I negotiated a discount and "
                    "the result was a signed annual contract."
                ),
            }
        ],
        coverage={
            "negotiation": {
                "status": "partial",
                "covered_intents": ["establish_context"],
                "missing_intents": ["establish_ownership", "applied_understanding"],
            }
        },
    )
    assert evidence
    scored = scorecard.competencies[0]
    assert scored.excerpts
    assert "establish_ownership" in scored.missing_intents
    assert scorecard.quality_metrics is not None
    assert scorecard.quality_metrics.validator_failure_rate == 0
    assert any("personally" in item.lower() or "handled" in item.lower() for item in scorecard.next_human_questions)
