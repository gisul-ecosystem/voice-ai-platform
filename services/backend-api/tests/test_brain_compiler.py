"""Milestone 2: blueprint compiler tests."""
from __future__ import annotations

from datetime import datetime, timezone

from brain.compiler import compile_blueprint
from brain.extractors import extract_job_intelligence
from brain.publish import publish_definition, validate_for_publication
from models.brain import JobIntelligence, JobRoleSummary


def _approved_job() -> JobIntelligence:
    extracted = extract_job_intelligence(
        """
        Sales Executive

        Responsibilities
        - Build pipeline with mid-market accounts
        - Run discovery calls and demos

        Requirements
        - 3+ years B2B sales
        - Strong communication

        Skills
        - Negotiation
        - CRM hygiene
        """
    )
    return extracted.model_copy(
        update={
            "approved": True,
            "approved_at": datetime.now(timezone.utc),
            "role": JobRoleSummary(
                title="Sales Executive",
                target_level="mid",
                domain="Go-to-market",
            ),
        }
    )


def test_compiler_builds_domain_neutral_blueprint() -> None:
    draft = compile_blueprint(
        job_intelligence=_approved_job(),
        creator_competencies=["Discovery quality", "Negotiation"],
        duration_minutes=30,
    )
    assert draft.prompt_version == "interviewer-system-v2"
    assert 3 <= len(draft.competencies) <= 6
    assert len(draft.question_ladders) == len(draft.competencies)
    assert {ladder.competency_id for ladder in draft.question_ladders} == {
        item.id for item in draft.competencies
    }
    assert abs(sum(c.weight or 0 for c in draft.competencies) - 100.0) < 0.01
    for competency in draft.competencies:
        assert competency.evidence_expected
        assert competency.min_assessment_intents
        assert {anchor.rating for anchor in competency.rubric} >= {1, 3, 5}
    assert draft.allowed_probes
    assert draft.time_policy.duration_minutes == 30
    assert draft.scenario_bank
    assert all(not scenario.approved for scenario in draft.scenario_bank)


def test_compiler_respects_creator_competencies_first() -> None:
    draft = compile_blueprint(
        job_intelligence=_approved_job(),
        creator_competencies=["Pipeline discipline", "Stakeholder trust"],
        include_scenarios=False,
    )
    names = [item.name.lower() for item in draft.competencies]
    assert "pipeline discipline" in names
    assert "stakeholder trust" in names
    assert draft.scenario_bank == []


def test_compiled_approved_blueprint_can_publish() -> None:
    draft = compile_blueprint(job_intelligence=_approved_job())
    # Scenarios from compiler are AI-generated and unapproved — strip for publish.
    publishable = draft.model_copy(update={"scenario_bank": []})
    result = validate_for_publication(publishable)
    assert result.ok, [issue.code for issue in result.issues]
    published = publish_definition(publishable, published_by="creator@example.com")
    assert published.status == "published"
    assert published.definition_id.startswith("idef_")
    assert len(published.question_ladders) == len(published.competencies)


def test_technical_and_nontechnical_share_prompt_version() -> None:
    sales = compile_blueprint(job_intelligence=_approved_job())
    backend = extract_job_intelligence(
        "Senior Backend Engineer\n\nSkills\n- Python\n- FastAPI\n"
    ).model_copy(
        update={
            "approved": True,
            "approved_at": datetime.now(timezone.utc),
            "role": JobRoleSummary(title="Backend Engineer", target_level="senior"),
        }
    )
    eng = compile_blueprint(job_intelligence=backend)
    assert sales.prompt_version == eng.prompt_version == "interviewer-system-v2"
