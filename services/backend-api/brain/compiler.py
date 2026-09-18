"""Compile an interview blueprint draft from approved job intelligence.

Domain-neutral: the same ladder/prompt structure is used for technical and
non-technical roles. Exact question wording stays adaptive at runtime.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from brain.defaults import (
    DEFAULT_ALLOWED_PROBES,
    DEFAULT_ENDING_POLICY,
    DEFAULT_NON_ANSWER_POLICY,
    DEFAULT_PROMPT_VERSION,
    DEFAULT_SCORING_POLICY,
    DEFAULT_VOICE_POLICY,
    default_question_ladder,
    default_time_policy_for_duration,
)
from models.brain import (
    CompetencyDefinition,
    DurationMinutes,
    ExtractedItem,
    InterviewDefinitionDraft,
    JobIntelligence,
    RubricAnchor,
    ScenarioDefinition,
    SeniorityLevel,
)

_SLUG = re.compile(r"[^a-z0-9]+")
_MAX_COMPETENCIES = 6
_MIN_COMPETENCIES = 3

_CORE_FALLBACKS: list[tuple[str, str, str]] = [
    (
        "problem_solving",
        "Problem solving",
        "Identifies job-related problems and resolves them with sound judgment",
    ),
    (
        "communication",
        "Communication",
        "Explains work clearly to collaborators and stakeholders",
    ),
    (
        "ownership",
        "Ownership",
        "Takes responsibility for delivery, follow-through, and outcomes",
    ),
]

_LEVEL_TO_REQUIRED: dict[SeniorityLevel, int] = {
    "intern": 2,
    "junior": 3,
    "mid": 3,
    "senior": 4,
    "lead": 5,
}


def _slugify(value: str, *, fallback: str) -> str:
    cleaned = _SLUG.sub("_", (value or "").strip().lower()).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:62]


def _unique_id(base: str, used: set[str]) -> str:
    candidate = base
    if candidate not in used:
        used.add(candidate)
        return candidate
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    candidate = f"{base[:55]}_{digest}"
    used.add(candidate)
    return candidate


def _default_rubric(name: str) -> list[RubricAnchor]:
    return [
        RubricAnchor(
            rating=1,
            description=f"Little or no relevant evidence for {name.lower()}",
        ),
        RubricAnchor(
            rating=3,
            description=(
                f"Explains a relevant example for {name.lower()} with clear "
                "personal contribution and outcome"
            ),
        ),
        RubricAnchor(
            rating=5,
            description=(
                f"Shows strong {name.lower()} with trade-offs, alternatives, "
                "and measurable impact"
            ),
        ),
    ]


def _evidence_for(name: str, jd_hints: list[str]) -> list[str]:
    base = [
        "context of the work",
        "personal contribution",
        "approach or method",
        "result or impact",
    ]
    for hint in jd_hints[:2]:
        clipped = hint.strip()
        if clipped and clipped.lower() not in {item.lower() for item in base}:
            base.append(clipped[:120])
    if name.lower() not in " ".join(base).lower():
        base.append(f"example demonstrating {name.lower()}")
    return base[:12]


def _intents_for_level(level: SeniorityLevel) -> list[str]:
    intents = [
        "establish_context",
        "establish_ownership",
        "applied_understanding",
    ]
    if level in {"mid", "senior", "lead"}:
        intents.append("problem_or_complexity")
    if level in {"senior", "lead"}:
        intents.append("tradeoff_or_transfer")
    return intents


def _texts(items: Iterable[ExtractedItem]) -> list[str]:
    return [item.text.strip() for item in items if item.text and item.text.strip()]


def _candidate_competency_seeds(
    job: JobIntelligence,
    creator_competencies: list[str] | None,
) -> list[tuple[str, str, list[str]]]:
    """Return (id_base, display_name, jd_hint_texts)."""
    seeds: list[tuple[str, str, list[str]]] = []
    seen_names: set[str] = set()

    def add(name: str, hints: list[str]) -> None:
        cleaned = re.sub(r"\s+", " ", name).strip(" -•:")
        if len(cleaned) < 2:
            return
        key = cleaned.lower()
        if key in seen_names:
            return
        seen_names.add(key)
        seeds.append((_slugify(cleaned, fallback="competency"), cleaned[:120], hints))

    for name in creator_competencies or []:
        add(name, [])

    for item in job.skills + job.mandatory_requirements:
        # Prefer short skill-like phrases.
        text = item.text.strip()
        if "," in text or len(text) > 60:
            continue
        add(text, [text])

    for item in job.responsibilities[:4]:
        # Turn a duty into a competency-style label when short enough.
        text = item.text.strip()
        if 8 <= len(text) <= 48:
            add(text, [text])

    if len(seeds) < _MIN_COMPETENCIES:
        for competency_id, name, _definition in _CORE_FALLBACKS:
            if name.lower() not in seen_names:
                seeds.append((competency_id, name, []))
                seen_names.add(name.lower())
            if len(seeds) >= _MIN_COMPETENCIES:
                break

    return seeds[:_MAX_COMPETENCIES]


def _build_competency(
    *,
    competency_id: str,
    name: str,
    hints: list[str],
    level: SeniorityLevel,
    weight: float,
    definition: str | None = None,
) -> CompetencyDefinition:
    return CompetencyDefinition(
        id=competency_id,
        name=name,
        definition=(
            definition
            or (
                f"Assesses whether the candidate can demonstrate {name.lower()} "
                f"relevant to the {level} role using concrete work examples"
            )
        )[:1000],
        importance="high" if weight >= (100.0 / _MAX_COMPETENCIES) else "medium",
        required_level=_LEVEL_TO_REQUIRED.get(level, 3),
        evidence_expected=_evidence_for(name, hints),
        min_assessment_intents=_intents_for_level(level),
        max_depth=min(5, max(3, _LEVEL_TO_REQUIRED.get(level, 3) + 1)),
        max_probes=3 if level in {"intern", "junior"} else 4,
        rubric=_default_rubric(name),
        weight=round(weight, 2),
    )


def _equal_weights(count: int) -> list[float]:
    if count <= 0:
        return []
    base = round(100.0 / count, 2)
    weights = [base] * count
    weights[-1] = round(100.0 - sum(weights[:-1]), 2)
    return weights


def _scenario_bank(
    job: JobIntelligence,
    competencies: list[CompetencyDefinition],
) -> list[ScenarioDefinition]:
    if not competencies:
        return []
    primary = competencies[0]
    scenarios: list[ScenarioDefinition] = []
    for index, item in enumerate(job.work_scenarios[:2], start=1):
        scenarios.append(
            ScenarioDefinition(
                id=f"scen_{index}_{primary.id}"[:64],
                competency_id=primary.id,
                level=job.role.target_level,
                scenario=item.text[:2000],
                expected_evidence=primary.evidence_expected[:4],
                source="ai_generated",
                approved=False,
            )
        )
    if scenarios:
        return scenarios
    # Generic domain-neutral scenario suggestion (creator must approve).
    return [
        ScenarioDefinition(
            id=f"scen_baseline_{primary.id}"[:64],
            competency_id=primary.id,
            level=job.role.target_level,
            scenario=(
                f"Describe a realistic work situation for a {job.role.title} "
                f"where {primary.name.lower()} matters, and walk through how "
                "you would handle it."
            ),
            expected_evidence=primary.evidence_expected[:4],
            source="ai_generated",
            approved=False,
        )
    ]


def compile_blueprint(
    *,
    job_intelligence: JobIntelligence,
    title: str | None = None,
    language: str = "English",
    timezone: str = "UTC",
    duration_minutes: DurationMinutes = 30,
    creator_competencies: list[str] | None = None,
    resume_required: bool = False,
    include_scenarios: bool = True,
) -> InterviewDefinitionDraft:
    """Build a reviewable InterviewDefinitionDraft from JD intelligence."""
    if not job_intelligence.raw_job_description.strip():
        raise ValueError("job_intelligence.raw_job_description is required")

    level = job_intelligence.role.target_level
    seeds = _candidate_competency_seeds(job_intelligence, creator_competencies)
    weights = _equal_weights(len(seeds))
    used_ids: set[str] = set()
    competencies: list[CompetencyDefinition] = []

    core_defs = {item[0]: item[2] for item in _CORE_FALLBACKS}
    for (id_base, name, hints), weight in zip(seeds, weights, strict=True):
        competency_id = _unique_id(id_base, used_ids)
        competencies.append(
            _build_competency(
                competency_id=competency_id,
                name=name,
                hints=hints,
                level=level,
                weight=weight,
                definition=core_defs.get(id_base),
            )
        )

    ladders = [default_question_ladder(item.id) for item in competencies]
    role_title = job_intelligence.role.title.strip() or "Interview"
    draft_title = (title or f"{role_title} interview").strip()[:160]

    return InterviewDefinitionDraft(
        title=draft_title if len(draft_title) >= 2 else "Structured interview",
        language=(language or "English").strip()[:32] or "English",
        timezone=(timezone or "UTC").strip()[:64] or "UTC",
        job_intelligence=job_intelligence,
        competencies=competencies,
        question_ladders=ladders,
        allowed_probes=list(DEFAULT_ALLOWED_PROBES),
        scenario_bank=(
            _scenario_bank(job_intelligence, competencies) if include_scenarios else []
        ),
        time_policy=default_time_policy_for_duration(duration_minutes),
        non_answer_policy=DEFAULT_NON_ANSWER_POLICY,
        ending_policy=DEFAULT_ENDING_POLICY,
        voice_policy=DEFAULT_VOICE_POLICY,
        scoring_policy=DEFAULT_SCORING_POLICY,
        prompt_version=DEFAULT_PROMPT_VERSION,
        resume_required=resume_required,
    )
