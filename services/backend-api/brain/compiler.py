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


# JD boilerplate that gets extracted along with the actual skill name.
_LABEL_PREFIXES = re.compile(
    r"^(?:required|requirements?|must[- ]have|nice[- ]to[- ]have|preferred|essential|"
    r"desired|responsibilities|responsibility|skills?|experience(?:\s+(?:in|with))?|"
    r"strong|proven|solid|deep|hands[- ]on|excellent|good|expert(?:ise)?(?:\s+in)?|"
    r"knowledge\s+of|familiarity\s+with|proficiency\s+(?:in|with)|ability\s+to)"
    r"\s*[:\-–]?\s+",
    re.IGNORECASE,
)


def normalize_skill_label(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "")).strip(" -•:")
    if not cleaned:
        return cleaned
    # Strip stacked prefixes: "Required: strong data structures" -> "data structures".
    for _ in range(3):
        stripped = _LABEL_PREFIXES.sub("", cleaned, count=1).strip(" -•:")
        if stripped == cleaned or not stripped:
            break
        cleaned = stripped
    alias = _SKILL_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    # A label that is now a bare fragment is worse than the original.
    if len(cleaned) < 2:
        return re.sub(r"\s+", " ", (value or "")).strip(" -•:")
    return cleaned[:1].upper() + cleaned[1:]


def _evidence_for(name: str, jd_hints: list[str]) -> list[str]:
    """Technical evidence dimensions, not a STAR story template.

    These are what the answer must contain for the competency to count as proven.
    The interviewer writes its own wording; these only set the bar.
    """
    topic = (name or "this area").strip().lower()
    base = [
        f"what they personally decided or built in {topic}",
        f"the specific method, algorithm, pattern or tool used for {topic}, named",
        "how that approach works internally, step by step",
        "its cost characteristics: time/space complexity, latency, throughput or spend",
        "why that option over a named alternative, and what it cost them",
        "where the approach breaks: edge cases, failure modes, behaviour at scale",
        "how they would optimise it further, and the trade-off that would introduce",
        "a measured outcome stated as from-value to to-value",
    ]
    for hint in jd_hints[:2]:
        clipped = hint.strip()
        if clipped and clipped.lower() not in {item.lower() for item in base}:
            base.append(f"concrete evidence of {clipped[:100]}")
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
) -> list[tuple[str, str, list[str], bool, str]]:
    """Return (id_base, display_name, jd_hint_texts, required, source)."""
    seeds: list[tuple[str, str, list[str], bool, str]] = []
    seen_names: set[str] = set()

    def add(name: str, hints: list[str], *, required: bool, source: str = "jd") -> None:
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
            (
                _slugify(cleaned, fallback="competency"),
                cleaned[:120],
                hints,
                required,
                source,
            )
        )

    for name in creator_competencies or []:
        add(name, [], required=True, source="creator")

    # If the secondary LLM synthesis pass produced normalized core_competencies,
    # use those directly — they are already canonical (e.g. "Data Structures and
    # Algorithms" instead of "solid foundations in DSA"). Only fall through to the
    # raw-item extraction path when core_competencies is absent or empty.
    if not creator_competencies and job.core_competencies:
        for name in job.core_competencies:
            cleaned = (name or "").strip()
            if cleaned:
                add(cleaned, [cleaned], required=True, source="llm_synthesis")
    else:
        def _usable(item: ExtractedItem, *, max_len: int = 60) -> bool:
            text = item.text.strip()
            if "," in text or len(text) > max_len:
                return False
            if item.provenance.confidence < _MIN_SEED_CONFIDENCE:
                return False
            return True

        for item in job.skills + job.mandatory_requirements:
            if _usable(item):
                add(item.text, [item.text], required=True)

        for item in job.responsibilities[:4]:
            text = item.text.strip()
            if 8 <= len(text) <= 48 and item.provenance.confidence >= _MIN_SEED_CONFIDENCE:
                add(text, [text], required=True)

        preferred_pool = (
            list(job.preferred_requirements) + list(job.tools) + list(job.knowledge)
        )
        for item in preferred_pool:
            if _usable(item, max_len=48):
                add(item.text, [item.text], required=False)

    required_seeds = [seed for seed in seeds if seed[3]]
    preferred_seeds = [seed for seed in seeds if not seed[3]]
    combined = required_seeds + preferred_seeds

    if len(combined) < _MIN_COMPETENCIES:
        for competency_id, name, _definition in _CORE_FALLBACKS:
            if name.lower() not in seen_names:
                combined.append((competency_id, name, [], True, "fallback"))
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
    source: str = "jd",
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
        importance="high" if required else "medium",
        required_level=_LEVEL_TO_REQUIRED.get(level, 3),
        evidence_expected=_evidence_for(name, hints),
        min_assessment_intents=_intents_for_level(level),
        max_depth=min(5, max(3, _LEVEL_TO_REQUIRED.get(level, 3) + 1)),
        max_probes=3 if level in {"intern", "junior"} else 4,
        rubric=_role_rubric(name, level, hints),
        weight=round(weight, 2),
        source=source,  # type: ignore[arg-type]
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
        if contains_prohibited_content(item.text) or contains_prompt_injection(item.text):
            continue
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
    weights = _importance_weights([seed[3] for seed in seeds])
    used_ids: set[str] = set()
    competencies: list[CompetencyDefinition] = []

    core_defs = {item[0]: item[2] for item in _CORE_FALLBACKS}
    for (id_base, name, hints, required, source), weight in zip(seeds, weights, strict=True):
        competency_id = _unique_id(id_base, used_ids)
        competencies.append(
            _build_competency(
                competency_id=competency_id,
                name=name,
                hints=hints,
                level=level,
                weight=weight,
                required=required,
                definition=core_defs.get(id_base),
                source=source,
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
