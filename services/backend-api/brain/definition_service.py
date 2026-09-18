"""Helpers to publish and attach interview definitions to live contexts."""
from __future__ import annotations

import logging

from brain.compiler import compile_blueprint
from brain.llm_extract import extract_job_intelligence_async
from brain.publish import publish_definition
from db import definitions, interviews
from models.brain import DurationMinutes, InterviewDefinitionVersion, SeniorityLevel
from models.schemas import InterviewSetupConfig

logger = logging.getLogger("backend-api.brain.definitions")


async def publish_and_store(
    *,
    job_description: str,
    interview_setup: InterviewSetupConfig,
    timezone: str,
    published_by: str,
    existing_definition_id: str | None = None,
) -> InterviewDefinitionVersion:
    if existing_definition_id:
        stored = await definitions.get_definition_model(existing_definition_id)
        if stored is None:
            raise ValueError("definition_id not found")
        return stored

    if not interview_setup.competencies:
        raise ValueError("creator competencies are required to publish a definition")

    level: SeniorityLevel = interview_setup.seniority
    duration: DurationMinutes = interview_setup.durationMinutes
    job = await extract_job_intelligence_async(
        job_description,
        target_level=level,
        domain=None,
    )
    # Recruiter-named competencies are the review payload. Extract APIs never
    # stamp approved=True; schedule/publish only does so after this explicit list.
    job = job.model_copy(
        update={
            "approved": True,
            "approved_at": interviews.utc_now(),
            "role": job.role.model_copy(
                update={
                    "title": interview_setup.role.strip() or job.role.title,
                    "target_level": level,
                }
            ),
        }
    )
    logger.info(
        "job_intelligence_approved_for_publish",
        extra={
            "event": "job_intelligence_approved_for_publish",
            "source": "creator_competencies",
            "competency_count": len(interview_setup.competencies),
        },
    )
    draft = compile_blueprint(
        job_intelligence=job,
        title=interview_setup.title,
        language=interview_setup.language,
        timezone=timezone,
        duration_minutes=duration,
        creator_competencies=list(interview_setup.competencies),
        include_scenarios=False,
    )
    published = publish_definition(draft, published_by=published_by)
    outcome = await definitions.save_definition(published)
    logger.info(
        "interview_definition_persisted",
        extra={
            "event": "interview_definition_persisted",
            "definition_id": published.definition_id,
            "outcome": outcome,
        },
    )
    return published
