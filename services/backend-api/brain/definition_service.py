"""Helpers to publish and attach interview definitions to live contexts."""
from __future__ import annotations

import logging

from brain.compiler import compile_blueprint
from brain.llm_extract import (
    extract_job_intelligence_async,
)
from brain.publish import publish_definition
from db import definitions, interviews
from models.brain import DurationMinutes, InterviewDefinitionVersion, SeniorityLevel
from models.schemas import InterviewSetupConfig

logger = logging.getLogger("backend-api.brain.definitions")


_MIN_JD_CHARS = 20
_MIN_COMPETENCY_CHARS = 2


def _require_publishable_setup(
    *,
    job_description: str,
    interview_setup: InterviewSetupConfig,
) -> tuple[str, list[str]]:
    """Creator publication gates before compile/publish (incomplete setup blocked)."""
    jd = (job_description or "").strip()
    if len(jd) < _MIN_JD_CHARS:
        raise ValueError(
            "job description is incomplete; paste a full JD before publishing"
        )
    title = (interview_setup.title or "").strip()
    role = (interview_setup.role or "").strip()
    if len(title) < 2 or len(role) < 2:
        raise ValueError("interview title and role are required before publishing")
    competencies = [
        item.strip()
        for item in interview_setup.competencies
        if isinstance(item, str) and item.strip()
    ]
    if not competencies:
        raise ValueError("creator competencies are required to publish a definition")
    if any(len(item) < _MIN_COMPETENCY_CHARS for item in competencies):
        raise ValueError("each competency must be a real skill name, not a blank token")
    return jd, competencies


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

    jd, competencies = _require_publishable_setup(
        job_description=job_description,
        interview_setup=interview_setup,
    )
    interview_setup = interview_setup.model_copy(update={"competencies": competencies})

    level: SeniorityLevel = interview_setup.seniority
    duration: DurationMinutes = interview_setup.durationMinutes
    job = await extract_job_intelligence_async(
        jd,
        target_level=level,
        domain=None,
    )
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
    # Setup competencies already structure the interview (design/review or
    # explicit chips). Do not re-run LLM recommend and replace that structure.
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
        creator_exclusive=True,
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
