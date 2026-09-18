"""Milestone 0: interview brain schema and publication rules."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from brain.defaults import (
    DEFAULT_NON_ANSWER_POLICY,
    DEFAULT_TIME_POLICY,
    default_question_ladder,
    default_time_policy_for_duration,
)
from brain.publish import publish_definition, validate_for_publication
from models.brain import (
    CompetencyDefinition,
    InterviewDefinitionDraft,
    JobIntelligence,
    JobRoleSummary,
    RubricAnchor,
    SourceReference,
    TimePolicy,
)


def _provenance(**kwargs) -> SourceReference:
    return SourceReference(
        source="jd",
        source_span="Build and maintain reliable services",
        confidence=0.9,
        confirmed=True,
        **kwargs,
    )


def _competency(
    competency_id: str = "problem_solving",
    *,
    weight: float | None = None,
) -> CompetencyDefinition:
    return CompetencyDefinition(
        id=competency_id,
        name="Problem solving",
        definition="Identifies and resolves job-related problems effectively",
        evidence_expected=["problem", "action", "reasoning", "result"],
        min_assessment_intents=["problem", "action", "result"],
        max_depth=4,
        max_probes=3,
        rubric=[
            RubricAnchor(rating=1, description="No relevant problem or action"),
            RubricAnchor(
                rating=3,
                description="Explains a relevant problem, action and result",
            ),
            RubricAnchor(
                rating=5,
                description="Explains complex problem, alternatives and measured outcome",
            ),
        ],
        weight=weight,
    )


def _approved_job(title: str = "Backend Engineer") -> JobIntelligence:
    return JobIntelligence(
        role=JobRoleSummary(title=title, target_level="junior", domain="Technology"),
        raw_job_description=(
            "We need a Backend Engineer who can build APIs, debug production "
            "issues, and collaborate with product teams."
        ),
        approved=True,
        approved_at=datetime.now(timezone.utc),
    )


def _draft(**overrides) -> InterviewDefinitionDraft:
    payload = {
        "title": "Backend screen",
        "language": "English",
        "timezone": "Asia/Kolkata",
        "job_intelligence": _approved_job(),
        "competencies": [_competency()],
        "time_policy": DEFAULT_TIME_POLICY,
        "non_answer_policy": DEFAULT_NON_ANSWER_POLICY,
    }
    payload.update(overrides)
    return InterviewDefinitionDraft(**payload)


def test_rubric_requires_anchors_for_1_3_and_5() -> None:
    with pytest.raises(ValidationError):
        CompetencyDefinition(
            id="communication",
            name="Communication",
            definition="Communicates clearly with stakeholders",
            evidence_expected=["clarity"],
            min_assessment_intents=["clarity"],
            rubric=[
                RubricAnchor(rating=2, description="Weak"),
                RubricAnchor(rating=3, description="Ok"),
                RubricAnchor(rating=4, description="Good"),
            ],
        )


def test_time_policy_rejects_unordered_boundaries() -> None:
    with pytest.raises(ValidationError):
        TimePolicy(
            duration_minutes=30,
            soft_end_minutes=32,
            target_end_minutes=30,
            hard_end_minutes=35,
        )


def test_default_time_policy_scales_with_duration() -> None:
    policy = default_time_policy_for_duration(15)
    assert policy.soft_end_minutes == 12
    assert policy.target_end_minutes == 15
    assert policy.hard_end_minutes == 20


def test_publication_requires_approved_job_intelligence() -> None:
    draft = _draft(
        job_intelligence=JobIntelligence(
            role=JobRoleSummary(title="Sales Executive", target_level="junior"),
            raw_job_description="Sell B2B software to mid-market customers.",
            approved=False,
        )
    )
    result = validate_for_publication(draft)
    assert result.ok is False
    assert any(issue.code == "jd_not_approved" for issue in result.issues)


def test_publication_rejects_partial_and_invalid_weights() -> None:
    draft = _draft(
        competencies=[
            _competency("problem_solving", weight=60),
            CompetencyDefinition(
                id="communication",
                name="Communication",
                definition="Communicates clearly with customers and teammates",
                evidence_expected=["clarity", "audience"],
                min_assessment_intents=["clarity"],
                rubric=[
                    RubricAnchor(rating=1, description="Unclear"),
                    RubricAnchor(rating=3, description="Clear enough"),
                    RubricAnchor(rating=5, description="Persuasive and precise"),
                ],
                weight=None,
            ),
        ]
    )
    result = validate_for_publication(draft)
    assert any(issue.code == "partial_weights" for issue in result.issues)


def test_publication_rejects_prohibited_scenario_content() -> None:
    from models.brain import ScenarioDefinition

    draft = _draft(
        scenario_bank=[
            ScenarioDefinition(
                id="scn_1",
                competency_id="problem_solving",
                level="junior",
                scenario="Ask about the candidate's marital status before continuing.",
                expected_evidence=["judgment"],
                source="creator",
                approved=True,
            )
        ]
    )
    result = validate_for_publication(draft)
    assert any(issue.code == "prohibited_content" for issue in result.issues)


def test_publish_freezes_immutable_definition_and_fills_ladders() -> None:
    draft = _draft()
    published = publish_definition(draft, published_by="creator_1", version=1)

    assert published.status == "published"
    assert published.version == 1
    assert published.published_by == "creator_1"
    assert published.definition_id.startswith("idef_")
    assert published.template_id.startswith("tmpl_")
    assert len(published.question_ladders) == 1
    assert published.question_ladders[0].competency_id == "problem_solving"
    assert published.question_ladders[0].levels[0].intent == "establish_context"


def test_publish_raises_when_validation_fails() -> None:
    draft = _draft(
        job_intelligence=JobIntelligence(
            role=JobRoleSummary(title="Sales Executive", target_level="junior"),
            raw_job_description="Sell B2B software to mid-market customers.",
            approved=False,
        )
    )
    with pytest.raises(ValueError, match="not publishable"):
        publish_definition(draft, published_by="creator_1")


def test_default_ladder_is_domain_neutral() -> None:
    ladder = default_question_ladder("customer_negotiation")
    joined = " ".join(
        f"{step.intent} {step.objective} {step.example_question or ''}"
        for step in ladder.levels
    ).lower()
    assert "api" not in joined
    assert "database" not in joined
    assert "ownership" in joined
