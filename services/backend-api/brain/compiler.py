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
from brain.safety import contains_prohibited_content, contains_prompt_injection
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
_MIN_SEED_CONFIDENCE = 0.5
_REQUIRED_WEIGHT_MASS = 70.0
_PREFERRED_WEIGHT_MASS = 30.0

_SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "javascript": "javascript",
    "node": "node.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "py": "python",
    "python3": "python",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "golang": "go",
    "react.js": "react",
    "reactjs": "react",
    "tf": "tensorflow",
    "communication skills": "communication",
    "ms excel": "excel",
}

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


def _role_rubric(
    name: str,
    level: SeniorityLevel,
    hints: list[str],
) -> list[RubricAnchor]:
    hint = (hints[0] if hints else name).strip()[:80] or name
    return [
        RubricAnchor(
            rating=1,
            description=(
                f"Little or no observable evidence of {name.lower()} at the "
                f"{level} level (no concrete {hint.lower()} example)"
            )[:500],
        ),
        RubricAnchor(
            rating=3,
            description=(
                f"Describes a relevant {name.lower()} example for a {level} "
                f"role, including personal contribution and a clear outcome "
                f"related to {hint.lower()}"
            )[:500],
        ),
        RubricAnchor(
            rating=5,
            description=(
                f"Shows strong {name.lower()} for a {level} role, including "
                f"trade-offs, alternatives, and measurable impact related to "
                f"{hint.lower()}"
            )[:500],
        ),
    ]


def normalize_skill_label(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "")).strip(" -•:")
    if not cleaned:
        return cleaned
    alias = _SKILL_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    return cleaned


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
    *,
    creator_exclusive: bool = False,
) -> list[tuple[str, str, list[str], bool]]:
    """Return (id_base, display_name, jd_hint_texts, required)."""
    seeds: list[tuple[str, str, list[str], bool]] = []
    seen_names: set[str] = set()

    def add(name: str, hints: list[str], *, required: bool) -> None:
        cleaned = normalize_skill_label(name)
        if len(cleaned) < 2:
            return
        if contains_prohibited_content(cleaned) or contains_prompt_injection(cleaned):
            return
        key = cleaned.lower()
        if key in seen_names:
            return
        seen_names.add(key)
        seeds.append(
            (_slugify(cleaned, fallback="competency"), cleaned[:120], hints, required)
        )

    for name in creator_competencies or []:
        add(name, [], required=True)

    # LLM / explicit creator recommendations should own the interview plan.
    # Only fall back to JD fragment heuristics when we do not have enough.
    skip_jd_pad = creator_exclusive and len(seeds) >= _MIN_COMPETENCIES

    def _usable(item: ExtractedItem, *, max_len: int = 96) -> bool:
        text = item.text.strip()
        # Allow comma-separated skill lists by using the first segment when long.
        if "," in text:
            text = text.split(",", 1)[0].strip()
        if len(text) < 2 or len(text) > max_len:
            return False
        if item.provenance.confidence < _MIN_SEED_CONFIDENCE:
            return False
        return True

    if not skip_jd_pad:
        for item in job.skills + job.mandatory_requirements:
            if _usable(item):
                label = item.text.strip()
                if "," in label:
                    label = label.split(",", 1)[0].strip()
                add(label, [item.text], required=True)

        for item in job.responsibilities[:4]:
            text = item.text.strip()
            if 8 <= len(text) <= 72 and item.provenance.confidence >= _MIN_SEED_CONFIDENCE:
                add(text, [text], required=True)

        preferred_pool = (
            list(job.preferred_requirements) + list(job.tools) + list(job.knowledge)
        )
        for item in preferred_pool:
            if _usable(item, max_len=72):
                label = item.text.strip()
                if "," in label:
                    label = label.split(",", 1)[0].strip()
                add(label, [item.text], required=False)

    required_seeds = [seed for seed in seeds if seed[3]]
    preferred_seeds = [seed for seed in seeds if not seed[3]]
    combined = required_seeds + preferred_seeds

    if len(combined) < _MIN_COMPETENCIES:
        for competency_id, name, _definition in _CORE_FALLBACKS:
            if name.lower() not in seen_names:
                combined.append((competency_id, name, [], True))
                seen_names.add(name.lower())
            if len(combined) >= _MIN_COMPETENCIES:
                break

    return combined[:_MAX_COMPETENCIES]


def _build_competency(
    *,
    competency_id: str,
    name: str,
    hints: list[str],
    level: SeniorityLevel,
    weight: float,
    required: bool = True,
    definition: str | None = None,
    evidence_expected: list[str] | None = None,
) -> CompetencyDefinition:
    evidence = [item.strip() for item in (evidence_expected or []) if item and item.strip()]
    if not evidence:
        evidence = _evidence_for(name, hints)
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
        importance="high" if required else "medium",
        required_level=_LEVEL_TO_REQUIRED.get(level, 3),
        evidence_expected=evidence[:12],
        min_assessment_intents=_intents_for_level(level),
        max_depth=min(5, max(3, _LEVEL_TO_REQUIRED.get(level, 3) + 1)),
        max_probes=3 if level in {"intern", "junior"} else 4,
        rubric=_role_rubric(name, level, hints),
        weight=round(weight, 2),
    )


def _equal_weights(count: int) -> list[float]:
    if count <= 0:
        return []
    base = round(100.0 / count, 2)
    weights = [base] * count
    weights[-1] = round(100.0 - sum(weights[:-1]), 2)
    return weights


def _importance_weights(required_flags: list[bool]) -> list[float]:
    if not required_flags:
        return []
    n_req = sum(1 for flag in required_flags if flag)
    n_pref = len(required_flags) - n_req
    if n_req == 0 or n_pref == 0:
        return _equal_weights(len(required_flags))
    weights: list[float] = []
    req_each = round(_REQUIRED_WEIGHT_MASS / n_req, 2)
    pref_each = round(_PREFERRED_WEIGHT_MASS / n_pref, 2)
    req_assigned = 0.0
    pref_assigned = 0.0
    req_seen = 0
    pref_seen = 0
    for flag in required_flags:
        if flag:
            req_seen += 1
            if req_seen == n_req:
                weights.append(round(_REQUIRED_WEIGHT_MASS - req_assigned, 2))
            else:
                weights.append(req_each)
                req_assigned += req_each
        else:
            pref_seen += 1
            if pref_seen == n_pref:
                weights.append(round(_PREFERRED_WEIGHT_MASS - pref_assigned, 2))
            else:
                weights.append(pref_each)
                pref_assigned += pref_each
    drift = round(100.0 - sum(weights), 2)
    if weights:
        weights[-1] = round(weights[-1] + drift, 2)
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
        text = " ".join(item.text.split())
        if len(text) < 8:
            continue
        if contains_prohibited_content(text) or contains_prompt_injection(text):
            continue
        scenarios.append(
            ScenarioDefinition(
                id=f"scen_{index}_{primary.id}"[:64],
                competency_id=primary.id,
                level=job.role.target_level,
                scenario=text[:2000],
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
    recommended_competencies: list[dict] | None = None,
    creator_exclusive: bool = False,
    resume_required: bool = False,
    include_scenarios: bool = True,
) -> InterviewDefinitionDraft:
    """Build a reviewable InterviewDefinitionDraft from JD intelligence.

    Competencies are the interview structure. Prefer LLM recommendations when
    provided; otherwise seed from creator guidance + JD heuristics.
    """
    if not job_intelligence.raw_job_description.strip():
        raise ValueError("job_intelligence.raw_job_description is required")

    level = job_intelligence.role.target_level
    enrichment: dict[str, dict] = {}
    seed_names = list(creator_competencies or [])
    exclusive = creator_exclusive

    if recommended_competencies:
        seed_names = []
        for item in recommended_competencies:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if len(name) < 2:
                continue
            seed_names.append(name)
            # Key by normalized label so lookup survives aliasing (js→javascript).
            enrichment[normalize_skill_label(name).lower()] = item
            enrichment[name.lower()] = item
        exclusive = True

    seeds = _candidate_competency_seeds(
        job_intelligence,
        seed_names,
        creator_exclusive=exclusive,
    )
    weights = _importance_weights([seed[3] for seed in seeds])
    used_ids: set[str] = set()
    competencies: list[CompetencyDefinition] = []

    core_defs = {item[0]: item[2] for item in _CORE_FALLBACKS}
    for (id_base, name, hints, required), weight in zip(seeds, weights, strict=True):
        competency_id = _unique_id(id_base, used_ids)
        enriched = (
            enrichment.get(name.lower())
            or enrichment.get(normalize_skill_label(name).lower())
            or {}
        )
        llm_definition = str(enriched.get("definition") or "").strip() or None
        llm_evidence = enriched.get("evidence_expected")
        evidence_list = (
            [str(x).strip() for x in llm_evidence if str(x).strip()]
            if isinstance(llm_evidence, list)
            else None
        )
        if enriched and "required" in enriched:
            required = bool(enriched.get("required"))
        competencies.append(
            _build_competency(
                competency_id=competency_id,
                name=name,
                hints=hints,
                level=level,
                weight=weight,
                required=required,
                definition=llm_definition or core_defs.get(id_base),
                evidence_expected=evidence_list,
            )
        )

    ladders = [
        default_question_ladder(item.id, item.name)
        for item in competencies
    ]
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
