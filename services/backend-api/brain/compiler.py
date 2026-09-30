"""Compile an interview blueprint draft from approved job intelligence.

Domain-neutral: the same ladder/prompt structure is used for technical and
non-technical roles. Exact question wording stays adaptive at runtime.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from brain import blueprint_formula
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
    LevelAnchors,
    QuestioningMode,
    RigorLevel,
    RubricAnchor,
    ScenarioDefinition,
    SectionDefinition,
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


# Bare verbs / duty fragments from comma-splitting JD responsibility lines.
# These are not interviewable competency titles.
_BARE_DUTY_TOKENS = frozenset(
    {
        "design",
        "designs",
        "designing",
        "develop",
        "develops",
        "developing",
        "test",
        "tests",
        "testing",
        "build",
        "builds",
        "building",
        "maintain",
        "maintains",
        "maintaining",
        "create",
        "implement",
        "manage",
        "support",
        "analyze",
        "optimize",
        "deploy",
        "write",
        "code",
    }
)


def is_interviewable_competency_label(value: str) -> bool:
    """Reject JD duty fragments that should never become interview phases.

    Blocks bare verbs (Design/develop/test), leading ``and …`` scraps, and
    long comma-heavy responsibility sentences pasted as competency names.
    Real skill titles like ``Python``, ``Negotiation``, ``Role expertise`` pass.
    """
    cleaned = normalize_skill_label(value)
    if len(cleaned) < 3:
        return False
    words = [w for w in re.split(r"\s+", cleaned) if w]
    if not words:
        return False
    first = words[0].lower().strip(".,;:")
    if first in {"and", "or", "the", "a", "an", "to", "of", "for", "with"}:
        return False
    if len(words) == 1 and first in _BARE_DUTY_TOKENS:
        return False
    # Comma-split duty residue: "and maintain applications using Python."
    if cleaned.lower().startswith("and "):
        return False
    # Full responsibility sentence used as a label (too long + clause-like).
    if len(cleaned) > 72 and ("," in cleaned or cleaned.count(" ") >= 8):
        return False
    return True


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
        if not is_interviewable_competency_label(cleaned):
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

    # Creator-provided chips own the plan. Never invent phases from JD duty lines.
    skip_jd_pad = creator_exclusive or len(seeds) >= _MIN_COMPETENCIES

    def _usable(item: ExtractedItem, *, max_len: int = 96) -> bool:
        text = item.text.strip()
        # Do not take the first comma segment of a duty line ("Design, develop…").
        # Only accept compact skill labels without clause punctuation.
        if "," in text or ";" in text:
            return False
        if len(text) < 3 or len(text) > max_len:
            return False
        if not is_interviewable_competency_label(text):
            return False
        if item.provenance.confidence < _MIN_SEED_CONFIDENCE:
            return False
        return True

    if not skip_jd_pad:
        for item in job.skills + job.mandatory_requirements:
            if _usable(item):
                add(item.text.strip(), [item.text], required=True)

        # Responsibilities are duties, not competency titles — never seed phases
        # from them (that produced Design/develop/test fragments).

        preferred_pool = (
            list(job.preferred_requirements) + list(job.tools) + list(job.knowledge)
        )
        for item in preferred_pool:
            if _usable(item, max_len=72):
                add(item.text.strip(), [item.text], required=False)

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
    allowed_intents: list[str] | None = None,
    evaluation_lens: str | None = None,
    level_anchors: LevelAnchors | None = None,
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
        allowed_intents=[item.strip() for item in (allowed_intents or []) if item.strip()] or None,
        evaluation_lens=(evaluation_lens or "").strip()[:200] or None,
        level_anchors=level_anchors,
    )


def _anchors_from_rubric(rubric: list[RubricAnchor]) -> LevelAnchors:
    """Derive weak/strong anchors from the 1/5 rubric anchors (spec 4.4)."""
    by_rating = {anchor.rating: anchor.description for anchor in rubric}
    weak = by_rating.get(1) or next(iter(rubric)).description
    strong = by_rating.get(5) or rubric[-1].description
    return LevelAnchors(weak=weak[:500], strong=strong[:500])


def _apply_weight_formula(
    competency: CompetencyDefinition,
    *,
    weight: float,
) -> CompetencyDefinition:
    """Populate formula-driven behaviour fields (spec 4.1).

    Admins only move the weight slider; the deterministic conversion lives
    in brain/blueprint_formula.py.
    """
    return competency.model_copy(
        update={
            "required_questions": blueprint_formula.required_questions(weight),
            "max_probes": blueprint_formula.max_probes(weight),
            "depth_target": blueprint_formula.depth_target(weight),
            "level_anchors": competency.level_anchors
            or _anchors_from_rubric(competency.rubric),
        }
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


def _resolve_sections(
    *,
    sections: list[SectionDefinition] | None,
    competencies: list[CompetencyDefinition],
    questioning_mode: QuestioningMode,
    duration_minutes: DurationMinutes,
    formula_mode: bool,
) -> list[SectionDefinition]:
    """Choose the section plan for the draft (spec 4.4).

    Caller-provided sections win only when they reference compiled competency
    ids exactly; otherwise legacy drafts get no sections and formula-mode
    drafts get one auto-grouped section covering every competency.
    """
    if not competencies:
        return []
    known_ids = {item.id for item in competencies}
    if sections:
        referenced: set[str] = set()
        usable = True
        for section in sections:
            for competency_id in section.competency_ids:
                if competency_id not in known_ids or competency_id in referenced:
                    usable = False
                    break
                referenced.add(competency_id)
            if not usable:
                break
        if usable and referenced == known_ids:
            return sorted(sections, key=lambda section: section.order)
    if not formula_mode:
        return []
    return [
        SectionDefinition(
            id="competency_assessment",
            order=1,
            type=questioning_mode,
            max_minutes=int(duration_minutes),
            competency_ids=[item.id for item in competencies],
            is_warmup=False,
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
    competency_weights: list[float] | None = None,
    questioning_mode: QuestioningMode = "adaptive",
    sections: list[SectionDefinition] | None = None,
    rigor: RigorLevel = "balanced",
) -> InterviewDefinitionDraft:
    """Build a reviewable InterviewDefinitionDraft from JD intelligence.

    Competencies are the interview structure. Prefer LLM recommendations when
    provided; otherwise seed from creator guidance + JD heuristics.

    Weight-formula mode (spec 4.1/4.4): when ``competency_weights`` is
    provided (or the caller explicitly opts in via non-default
    ``questioning_mode``/``rigor``), raw slider weights are normalized to a
    mass of 100 and converted into required_questions / max_probes /
    depth_target, and the draft gains explicit sections. With no weight input
    the legacy level-based behaviour is emitted unchanged.
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
    # Weight-formula mode (spec 4.1): explicit slider weights win when they
    # line up with the seeded competencies; otherwise legacy mass-splitting.
    formula_mode = (
        competency_weights is not None
        or questioning_mode != "adaptive"
        or rigor != "balanced"
        or bool(sections)
    )
    if (
        formula_mode
        and competency_weights is not None
        and len(competency_weights) == len(seeds)
    ):
        weights = blueprint_formula.normalize_weights(competency_weights)
    else:
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
        llm_intents = enriched.get("allowed_intents")
        intents_list = (
            [str(x).strip() for x in llm_intents if str(x).strip()]
            if isinstance(llm_intents, list)
            else None
        )
        llm_lens = str(enriched.get("evaluation_lens") or "").strip() or None
        anchors_raw = enriched.get("level_anchors")
        level_anchors = None
        if isinstance(anchors_raw, dict):
            weak = str(anchors_raw.get("weak") or "").strip()
            strong = str(anchors_raw.get("strong") or "").strip()
            if len(weak) >= 4 and len(strong) >= 4:
                level_anchors = LevelAnchors(weak=weak[:500], strong=strong[:500])
        if enriched and "required" in enriched:
            required = bool(enriched.get("required"))
        competency = _build_competency(
            competency_id=competency_id,
            name=name,
            hints=hints,
            level=level,
            weight=weight,
            required=required,
            definition=llm_definition or core_defs.get(id_base),
            evidence_expected=evidence_list,
            allowed_intents=intents_list,
            evaluation_lens=llm_lens,
            level_anchors=level_anchors,
        )
        if formula_mode:
            competency = _apply_weight_formula(competency, weight=weight)
        competencies.append(competency)

    ladders = [
        default_question_ladder(item.id, item.name)
        for item in competencies
    ]
    role_title = job_intelligence.role.title.strip() or "Interview"
    draft_title = (title or f"{role_title} interview").strip()[:160]

    final_sections = _resolve_sections(
        sections=sections,
        competencies=competencies,
        questioning_mode=questioning_mode,
        duration_minutes=duration_minutes,
        formula_mode=formula_mode,
    )

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
        sections=final_sections,
        rigor=rigor,
    )
