"""Publication validation and immutable definition versioning."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from brain.defaults import default_question_ladder
from brain.safety import PROHIBITED_PATTERNS
from models.brain import (
    InterviewDefinitionDraft,
    InterviewDefinitionVersion,
    PublicationIssue,
    PublicationValidationResult,
)


def validate_for_publication(
    draft: InterviewDefinitionDraft,
) -> PublicationValidationResult:
    issues: list[PublicationIssue] = []

    if not draft.title.strip():
        issues.append(
            PublicationIssue(
                code="missing_title",
                message="Interview title is required.",
                field="title",
            )
        )

    role = draft.job_intelligence.role
    if not role.title.strip():
        issues.append(
            PublicationIssue(
                code="missing_role",
                message="Role title is required.",
                field="job_intelligence.role.title",
            )
        )

    if not draft.job_intelligence.approved:
        issues.append(
            PublicationIssue(
                code="jd_not_approved",
                message="Job intelligence must be reviewed and approved before publish.",
                field="job_intelligence.approved",
            )
        )

    if not draft.job_intelligence.raw_job_description.strip():
        issues.append(
            PublicationIssue(
                code="missing_jd",
                message="A job description or structured role requirements are required.",
                field="job_intelligence.raw_job_description",
            )
        )

    if not draft.competencies:
        issues.append(
            PublicationIssue(
                code="missing_competencies",
                message="At least one mandatory competency is required.",
                field="competencies",
            )
        )

    competency_ids = [item.id for item in draft.competencies]
    if len(competency_ids) != len(set(competency_ids)):
        issues.append(
            PublicationIssue(
                code="duplicate_competency_ids",
                message="Competency IDs must be unique.",
                field="competencies",
            )
        )

    weights = [c.weight for c in draft.competencies if c.weight is not None]
    if weights:
        if len(weights) != len(draft.competencies):
            issues.append(
                PublicationIssue(
                    code="partial_weights",
                    message="If any competency has a weight, all competencies must have weights.",
                    field="competencies.weight",
                )
            )
        elif abs(sum(weights) - 100.0) > 0.01:
            issues.append(
                PublicationIssue(
                    code="invalid_weights",
                    message="Competency weights must total 100.",
                    field="competencies.weight",
                )
            )

    ladder_by_competency = {
        ladder.competency_id: ladder for ladder in draft.question_ladders
    }
    for competency in draft.competencies:
        if not competency.evidence_expected:
            issues.append(
                PublicationIssue(
                    code="missing_evidence_expectations",
                    message=f"Competency '{competency.id}' needs evidence expectations.",
                    field=f"competencies.{competency.id}.evidence_expected",
                )
            )
        if not competency.rubric:
            issues.append(
                PublicationIssue(
                    code="missing_rubric",
                    message=f"Competency '{competency.id}' needs a scoring rubric.",
                    field=f"competencies.{competency.id}.rubric",
                )
            )
        if competency.id not in ladder_by_competency:
            # Ladders are auto-filled at publish time; absence is not a hard block.
            continue

    if draft.time_policy.target_end_minutes != draft.time_policy.duration_minutes:
        issues.append(
            PublicationIssue(
                code="invalid_time_policy",
                message="Target end must match interview duration.",
                field="time_policy",
            )
        )

    for scenario in draft.scenario_bank:
        if scenario.competency_id not in competency_ids:
            issues.append(
                PublicationIssue(
                    code="scenario_unknown_competency",
                    message=(
                        f"Scenario '{scenario.id}' references unknown competency "
                        f"'{scenario.competency_id}'."
                    ),
                    field=f"scenario_bank.{scenario.id}",
                )
            )
        if scenario.source == "ai_generated" and not scenario.approved:
            issues.append(
                PublicationIssue(
                    code="scenario_not_approved",
                    message=f"AI-generated scenario '{scenario.id}' must be approved.",
                    field=f"scenario_bank.{scenario.id}.approved",
                )
            )
        for pattern in PROHIBITED_PATTERNS:
            if pattern.search(scenario.scenario):
                issues.append(
                    PublicationIssue(
                        code="prohibited_content",
                        message=f"Scenario '{scenario.id}' contains prohibited content.",
                        field=f"scenario_bank.{scenario.id}",
                    )
                )
                break

    for probe in draft.allowed_probes:
        for pattern in PROHIBITED_PATTERNS:
            if pattern.search(probe):
                issues.append(
                    PublicationIssue(
                        code="prohibited_content",
                        message="An allowed probe contains prohibited content.",
                        field="allowed_probes",
                    )
                )
                break

    if draft.ending_policy.announce_scores or draft.ending_policy.announce_hiring_decision:
        issues.append(
            PublicationIssue(
                code="unsafe_ending_policy",
                message="Ending policy must not announce scores or hiring decisions.",
                field="ending_policy",
            )
        )

    if draft.voice_policy.fallback_policy == "allow_provider_fallback":
        # Allowed but warned via issue that is non-blocking? Plan says silent switch
        # is disallowed by default. Keep as hard block for Milestone 0 defaults.
        issues.append(
            PublicationIssue(
                code="unsafe_voice_fallback",
                message=(
                    "Provider voice fallback is disabled by default because it can "
                    "change interviewer voice mid-session."
                ),
                field="voice_policy.fallback_policy",
            )
        )

    return PublicationValidationResult(ok=not issues, issues=issues)


def publish_definition(
    draft: InterviewDefinitionDraft,
    *,
    template_id: str | None = None,
    version: int = 1,
    published_by: str,
    definition_id: str | None = None,
    now: datetime | None = None,
) -> InterviewDefinitionVersion:
    """Validate and freeze a draft into an immutable published definition."""
    result = validate_for_publication(draft)
    if not result.ok:
        codes = ", ".join(issue.code for issue in result.issues)
        raise ValueError(f"Interview definition is not publishable: {codes}")

    ladders = list(draft.question_ladders)
    existing = {ladder.competency_id for ladder in ladders}
    for competency in draft.competencies:
        if competency.id not in existing:
            ladders.append(default_question_ladder(competency.id))

    payload = draft.model_dump()
    payload["question_ladders"] = [ladder.model_dump() for ladder in ladders]
    return InterviewDefinitionVersion(
        **payload,
        definition_id=definition_id or f"idef_{uuid.uuid4().hex}",
        template_id=template_id or f"tmpl_{uuid.uuid4().hex}",
        version=version,
        published_at=now or datetime.now(timezone.utc),
        published_by=published_by,
        status="published",
    )
