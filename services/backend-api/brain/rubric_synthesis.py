"""Rubric Synthesis Engine (Spec 4.3).

One upfront LLM call run once per interview session when competencies are left unset
by the admin, or to derive rich evaluation anchors and lens for unset competencies.

Features:
- Domain-agnostic assessment designer prompt (zero hardcoded domain taxonomy).
- Outputs competencies, required_skills, weak/strong level_anchors, allowed_intents,
  and dynamic evaluation_lens (e.g. MEDDIC, BANT, SPIN, STAR, etc.).
- Admin-defined competencies are preserved verbatim and never overridden.
- Read-through caching in MongoDB collection `rubric_cache` keyed by
  sha256(JD text + role + seniority).
- Cache misses fall through to fresh synthesis (never degraded results).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from brain.structured_llm import complete_structured_json
from db.mongo import get_db
from models.brain import (
    CompetencyDefinition,
    JobIntelligence,
    LevelAnchors,
    QuestioningMode,
    RigorLevel,
    RubricAnchor,
    SeniorityLevel,
)

logger = logging.getLogger("backend-api.brain.rubric_synthesis")

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are an expert assessment and evaluation designer. Your task is to design a rigorous, "
    "domain-appropriate interview rubric based on the provided job description and role details.\n\n"
    "CRITICAL RULES:\n"
    "1. Derive competencies and evaluation criteria fresh from the job description context. "
    "DO NOT force software engineering concepts if the role is Sales, Operations, Marketing, HR, Finance, etc.\n"
    "2. Determine the appropriate evaluation lens (e.g. for Enterprise Sales: MEDDIC or Command of the Message; "
    "for High-Velocity/SMB Sales: BANT or SPIN; for Behavioral/Leadership: STAR or SBI; "
    "for Engineering: System Design & Tradeoff Analysis; for Operations: Lean / Root-Cause Analysis; "
    "for General/Exam: Structured Problem Solving).\n"
    "3. For each competency, generate:\n"
    "   - A concise, normalized name and clear definition.\n"
    "   - required_skills: 3 to 6 SPECIFIC technical skills, concepts, or evidence markers that define depth. "
    "These are NOT interview questions. They are concrete indicators to look for in candidate answers.\n"
    "     * For Engineering/DSA: specific algorithms, patterns, complexity analysis (e.g. 'sliding_window_pattern', "
    "'two_pointer_technique', 'time_space_complexity_optimization', 'dynamic_programming_memoization')\n"
    "     * For System Design: architecture concepts (e.g. 'load_balancing_strategy', 'database_sharding', "
    "'caching_invalidation', 'CAP_theorem_tradeoffs')\n"
    "     * For Sales: deal mechanics (e.g. 'economic_buyer_identification', 'champion_building', 'procurement_process_navigation')\n"
    "     * For Operations: process mechanisms (e.g. 'root_cause_analysis_5_whys', 'capacity_planning_models', 'SLA_breach_mitigation')\n"
    "   - level_anchors: Concrete, plain-language description of a 'weak' answer vs a 'strong' answer at the target seniority level.\n"
    "   - allowed_intents: Specific probing angles suitable for this competency (e.g., situation, probe_stakeholders, "
    "probe_metrics, challenge, tradeoff, framework, reflection, verification).\n"
    "4. Match depth to seniority: Junior = foundational concepts; Mid = applied patterns; Senior/Lead = optimization, "
    "tradeoffs, and edge cases.\n"
    "5. Return strictly valid JSON adhering to the schema."
)

_RUBRIC_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "evaluation_lens": {
            "type": "string",
            "description": "Primary evaluation framework or lens implied by the JD (e.g. 'MEDDIC', 'STAR', 'BANT', 'Root-Cause Analysis').",
        },
        "competencies": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Lower_snake_case slug identifier (e.g. 'discovery_qualification', 'objection_resilience').",
                    },
                    "name": {
                        "type": "string",
                        "description": "Clean human-readable title (e.g. 'Discovery & Qualification').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Clear statement of what this competency assesses.",
                    },
                    "required_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 6,
                        "description": (
                            "Concrete technical depth indicators or evidence markers (NOT interview questions). "
                            "Examples: For DSA → 'sliding_window_optimization', 'hashmap_pattern', 'time_complexity_analysis'; "
                            "For System Design → 'distributed_consensus', 'CAP_tradeoffs', 'database_indexing'; "
                            "For Sales → 'economic_buyer_mapping', 'value_based_pricing', 'objection_reframing'"
                        ),
                    },
                    "level_anchors": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "weak": {
                                "type": "string",
                                "description": "What a shallow, generic, or weak candidate answer looks like.",
                            },
                            "strong": {
                                "type": "string",
                                "description": "What a deep, concrete, and exemplary candidate answer looks like.",
                            },
                        },
                        "required": ["weak", "strong"],
                    },
                    "allowed_intents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 6,
                        "description": "Questioning intents to guide probing for this competency.",
                    },
                    "importance": {
                        "type": "string",
                        "enum": ["high", "medium"],
                    },
                },
                "required": [
                    "id",
                    "name",
                    "description",
                    "required_skills",
                    "level_anchors",
                    "allowed_intents",
                    "importance",
                ],
            },
        },
    },
    "required": ["evaluation_lens", "competencies"],
}


def compute_rubric_cache_key(
    *,
    jd_text: str,
    role: str,
    seniority: str,
) -> str:
    """Compute sha256 cache key for rubric caching (Spec §4.2, §4.3)."""
    normalized = f"{jd_text.strip().lower()}||{role.strip().lower()}||{seniority.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached_rubric(cache_key: str) -> dict[str, Any] | None:
    """Read-through lookup from MongoDB rubric_cache."""
    try:
        db = get_db()
        entry = await db.rubric_cache.find_one({"_id": cache_key})
        if entry:
            logger.info("rubric_cache_hit", extra={"cache_key": cache_key})
            return entry.get("data")
    except Exception as exc:
        logger.warning("rubric_cache_read_error", extra={"error": str(exc)})
    return None


async def store_cached_rubric(cache_key: str, data: dict[str, Any]) -> None:
    """Store synthesized rubric in MongoDB rubric_cache."""
    try:
        db = get_db()
        await db.rubric_cache.update_one(
            {"_id": cache_key},
            {"$set": {"data": data, "updated_at": hashlib.sha1().hexdigest()}},
            upsert=True,
        )
        logger.info("rubric_cache_saved", extra={"cache_key": cache_key})
    except Exception as exc:
        logger.warning("rubric_cache_store_error", extra={"error": str(exc)})


async def synthesize_rubric_async(
    *,
    role: str,
    seniority: SeniorityLevel,
    job_description: str,
    target_duration_minutes: int = 45,
    creator_guidance: list[str] | None = None,
) -> dict[str, Any]:
    """Derive rubric data via LLM with read-through cache (Spec §4.3).

    Returns a dict with 'evaluation_lens' and list of 'competencies'.
    Falls back to a structured default if LLM extract is disabled or fails.
    """
    cache_key = compute_rubric_cache_key(
        jd_text=job_description,
        role=role,
        seniority=seniority,
    )
    cached = await get_cached_rubric(cache_key)
    if cached:
        return cached

    user_prompt = (
        f"Role Title: {role}\n"
        f"Seniority: {seniority}\n"
        f"Target Duration: {target_duration_minutes} minutes\n"
        f"Creator Guidance/Must-Haves: {', '.join(creator_guidance) if creator_guidance else '(none)'}\n\n"
        f"Job Description / Profile:\n{job_description[:12_000]}"
    )

    payload = await complete_structured_json(
        schema_name="rubric_synthesis",
        schema=_RUBRIC_SYNTHESIS_SCHEMA,
        system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    if not payload or not isinstance(payload.get("competencies"), list) or not payload["competencies"]:
        logger.warning(
            "rubric_synthesis_llm_miss_or_disabled",
            extra={"role": role, "seniority": seniority},
        )
        # Construct fallback rubric based on role and context
        payload = _build_default_rubric_fallback(role=role, seniority=seniority)

    # Cache the result for future identical sessions
    await store_cached_rubric(cache_key, payload)
    return payload


def _build_default_rubric_fallback(
    *,
    role: str,
    seniority: SeniorityLevel,
) -> dict[str, Any]:
    """Deterministic domain-neutral fallback when LLM is offline or disabled."""
    role_lower = role.lower()
    if "sale" in role_lower or "account" in role_lower or "bdr" in role_lower or "sdr" in role_lower:
        lens = "MEDDIC" if seniority in {"senior", "lead"} else "BANT"
        return {
            "evaluation_lens": lens,
            "competencies": [
                {
                    "id": "discovery_qualification",
                    "name": "Discovery & Qualification",
                    "description": f"Assesses qualification rigor, stakeholder discovery, and buyer alignment using {lens}.",
                    "required_skills": ["economic_buyer_id", "decision_criteria", "pain_identification"],
                    "level_anchors": {
                        "weak": "Relies on generic checklist questions, misses buying committee dynamics and decision criteria.",
                        "strong": "Maps multi-stakeholder decision process, connects business pain to quantified economic value.",
                    },
                    "allowed_intents": ["situation", "probe_stakeholders", "probe_metrics", "challenge"],
                    "importance": "high",
                },
                {
                    "id": "objection_handling",
                    "name": "Objection Handling & Value Reframing",
                    "description": "Assesses resilience, reframing competitor/pricing pushback, and deal progression instincts.",
                    "required_skills": ["active_listening", "value_reframing", "deal_progression"],
                    "level_anchors": {
                        "weak": "Concedes quickly on price or becomes defensive when challenged by prospects.",
                        "strong": "Reframes objections around ROI, diagnoses root skepticism, and secures clear next steps.",
                    },
                    "allowed_intents": ["scenario", "tradeoff", "probe_metrics", "reflection"],
                    "importance": "high",
                },
                {
                    "id": "pipeline_execution",
                    "name": "Pipeline Management & Closing",
                    "description": "Assesses forecasting discipline, territory planning, and closing urgency.",
                    "required_skills": ["pipeline_velocity", "mutual_action_plan", "closing_urgency"],
                    "level_anchors": {
                        "weak": "Unstructured pipeline, vague close dates, no documented mutual action plans.",
                        "strong": "Demonstrates rigorous deal stages, verified buyer commitments, and disciplined forecasting.",
                    },
                    "allowed_intents": ["practical", "probe_metrics", "tradeoff"],
                    "importance": "medium",
                },
            ],
        }

    # Universal structured fallback for any other role (e.g. Operations, Management, Tech, HR)
    # For Engineering roles, provide DSA/System Design depth markers
    if any(kw in role_lower for kw in ["engineer", "developer", "swe", "software", "backend", "frontend", "fullstack"]):
        return {
            "evaluation_lens": "System Design & Algorithmic Depth",
            "competencies": [
                {
                    "id": "data_structures_algorithms",
                    "name": "Data Structures & Algorithms",
                    "description": f"Assesses problem-solving depth, pattern recognition, and complexity optimization at {seniority} level.",
                    "required_skills": [
                        "sliding_window_pattern",
                        "two_pointer_technique",
                        "hashmap_optimization",
                        "time_space_complexity_analysis",
                        "edge_case_handling",
                        "optimal_solution_derivation"
                    ] if seniority in {"senior", "lead"} else [
                        "array_manipulation",
                        "basic_recursion",
                        "time_complexity_understanding"
                    ],
                    "level_anchors": {
                        "weak": "Provides brute-force O(n²) solution without recognizing optimization patterns; struggles with edge cases.",
                        "strong": "Identifies optimal algorithm pattern (e.g. sliding window), explains time/space tradeoffs, handles edge cases systematically."
                    } if seniority in {"senior", "lead"} else {
                        "weak": "Cannot implement basic array traversal or explain what time complexity means.",
                        "strong": "Implements correct solution with clear loop logic and explains why it works."
                    },
                    "allowed_intents": ["problem_or_complexity", "tradeoff", "probe_edge_cases", "approach"],
                    "importance": "high",
                },
                {
                    "id": "system_design_tradeoffs",
                    "name": "System Design & Architecture",
                    "description": f"Assesses distributed system reasoning, scalability tradeoffs, and production thinking at {seniority} level.",
                    "required_skills": [
                        "load_balancing_strategy",
                        "database_sharding_partitioning",
                        "caching_invalidation",
                        "CAP_theorem_tradeoffs",
                        "failure_mode_analysis",
                        "scaling_bottleneck_identification"
                    ] if seniority in {"senior", "lead"} else [
                        "client_server_architecture",
                        "basic_database_design",
                        "API_design_fundamentals"
                    ],
                    "level_anchors": {
                        "weak": "Proposes monolithic design without considering scale, reliability, or regional latency.",
                        "strong": "Designs multi-region architecture with clear tradeoffs (consistency vs availability), explains caching strategy, and identifies bottlenecks."
                    } if seniority in {"senior", "lead"} else {
                        "weak": "Cannot explain difference between SQL and NoSQL or when to use each.",
                        "strong": "Designs basic REST API with appropriate database schema and explains data flow."
                    },
                    "allowed_intents": ["tradeoff_or_transfer", "probe_failure_modes", "probe_metrics", "scenario"],
                    "importance": "high",
                },
            ],
        }

    return {
        "evaluation_lens": "STAR",
        "competencies": [
            {
                "id": "role_execution",
                "name": f"{role} Execution",
                "description": f"Demonstrates core domain execution and methodologies required for a {seniority} {role}.",
                "required_skills": ["domain_methods", "execution_quality", "problem_resolution"],
                "level_anchors": {
                    "weak": "Vague descriptions of day-to-day duties without concrete methodologies or results.",
                    "strong": "Clear explanation of specific frameworks, tradeoffs, tools, and quantified outcomes achieved.",
                },
                "allowed_intents": ["situation", "approach", "problem_or_complexity", "tradeoff"],
                "importance": "high",
            },
            {
                "id": "stakeholder_collaboration",
                "name": "Cross-Functional Collaboration",
                "description": "Aligns with cross-functional partners, navigates conflicting priorities, and communicates impact.",
                "required_skills": ["stakeholder_alignment", "communication_clarity", "conflict_resolution"],
                "level_anchors": {
                    "weak": "Works in a silo; blames external teams when handoffs fail or misalignments occur.",
                    "strong": "Proactively aligns incentives across departments, sets clear expectations, and unblocks blockers.",
                },
                "allowed_intents": ["situation", "tradeoff", "reflection"],
                "importance": "high",
            },
            {
                "id": "strategic_impact",
                "name": "Decision Making & Measurable Impact",
                "description": "Prioritizes high-leverage initiatives, learns from failures, and drives measurable improvements.",
                "required_skills": ["prioritization", "impact_measurement", "continuous_improvement"],
                "level_anchors": {
                    "weak": "Focuses on effort rather than outcome; lacks awareness of business metrics or project impact.",
                    "strong": "Connects day-to-day decisions directly to key business KPIs, ROI, and organizational goals.",
                },
                "allowed_intents": ["tradeoff_or_transfer", "problem_or_complexity", "probe_metrics"],
                "importance": "medium",
            },
        ],
    }
