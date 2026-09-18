"""Validate generated interview questions before they are spoken."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from products.interviewer.coverage import competency_by_id, ladder_steps

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

PROTECTED_MARKERS = (
    "age",
    "how old",
    "married",
    "children",
    "family status",
    "pregnant",
    "religion",
    "nationality",
    "ethnicity",
    "race",
    "gender",
    "disability",
    "accent",
    "native speaker",
    "where were you born",
    "maiden",
)

UNGROUNDED_TECH_TERMS = (
    "api",
    "schema",
    "queue",
    "kafka",
    "kubernetes",
    "redis",
    "postgres",
    "postgresql",
    "microservice",
    "latency",
    "deadlock",
    "index",
    "timeout",
    "http client",
    "websocket",
    "sharding",
)

INTENT_PROBE_ALIASES: dict[str, tuple[str, ...]] = {
    "establish_context": ("context", "situation", "describe"),
    "establish_ownership": ("responsibility", "personally", "owned", "your specific"),
    "applied_understanding": ("approach", "how did you", "method", "action"),
    "problem_or_complexity": ("difficult", "challenge", "failed", "constraint"),
    "tradeoff_or_transfer": ("change", "outcome", "result", "again", "alternative"),
    "clarify": ("clarify", "say a bit more", "full sentence"),
    "candidate_map": ("background", "introduce", "experience"),
    "opening": ("introduce", "background"),
    "baseline": ("example", "tell me about"),
    "final_addition": ("anything else", "add"),
    "gap_check": ("anything we have not", "one more"),
    "closing": ("thank", "concludes"),
    "recovery": ("move", "another"),
}


@dataclass
class GeneratedQuestion:
    question: str
    competency_id: str | None = None
    intent: str = "live_question"
    depth: int = 1
    source_claim_ids: list[str] = field(default_factory=list)
    decision: str = "probe"


@dataclass
class ValidationResult:
    ok: bool
    question: GeneratedQuestion
    reasons: list[str] = field(default_factory=list)


def fingerprint(text: str) -> str:
    cleaned = _PUNCT.sub(" ", (text or "").lower())
    return _WS.sub(" ", cleaned).strip()


def parse_generated_question(raw: str) -> GeneratedQuestion | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidate = text
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        match = _JSON_OBJECT.search(text)
        if match:
            candidate = match.group(0)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    question = str(payload.get("question") or "").strip()
    if not question:
        return None
    depth_raw = payload.get("depth") or 1
    try:
        depth = int(depth_raw)
    except (TypeError, ValueError):
        depth = 1
    claim_ids = [
        str(item).strip()
        for item in (payload.get("source_claim_ids") or [])
        if str(item).strip()
    ]
    competency_id = str(payload.get("competency_id") or "").strip() or None
    return GeneratedQuestion(
        question=question,
        competency_id=competency_id,
        intent=str(payload.get("intent") or "live_question").strip() or "live_question",
        depth=max(1, min(5, depth)),
        source_claim_ids=claim_ids,
        decision=str(payload.get("decision") or "probe").strip().lower() or "probe",
    )


def ladder_fallback_question(
    definition: dict[str, Any] | None,
    *,
    competency_id: str | None,
    intent: str,
) -> str:
    for step in ladder_steps(definition, competency_id):
        if str(step.get("intent") or "").strip() == intent:
            example = str(step.get("example_question") or "").strip()
            if example:
                return example
    defaults = {
        "establish_context": "Can you briefly describe the situation?",
        "establish_ownership": "What part of that did you personally handle?",
        "applied_understanding": "How did you approach that work?",
        "problem_or_complexity": "What was difficult about that, and how did you handle it?",
        "tradeoff_or_transfer": "Looking back, what would you change and why?",
        "candidate_map": "Please share a short overview of the work most relevant to this role.",
        "opening": (
            "Thanks for joining. I'm your interviewer for this conversation. "
            "To get started, please introduce yourself — a short overview of your "
            "background, and the work that is most relevant to this role."
        ),
        "clarify": "Sorry, I did not catch that. Please say a bit more, in a full sentence.",
        "final_addition": "Before we close, is there one example you would still like to add?",
    }
    return defaults.get(
        intent,
        "Could you share one specific example of work you personally handled, and what happened as a result?",
    )


def _allowed_claim_ids(profile: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()
    if not isinstance(profile, dict):
        return ids
    for item in profile.get("claims") or []:
        if isinstance(item, dict) and item.get("claim_id"):
            ids.add(str(item["claim_id"]).strip())
    return ids


def _grounding_corpus(
    *,
    definition: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    job_description: str,
    resume_text: str,
    recent_turns: list[str],
    competency_id: str | None,
) -> str:
    parts = [job_description or "", resume_text or ""]
    parts.extend(recent_turns)
    competency = competency_by_id(definition, competency_id)
    parts.append(str(competency.get("name") or ""))
    parts.append(str(competency.get("definition") or ""))
    if isinstance(profile, dict):
        for item in profile.get("claims") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("value") or ""))
    return " ".join(parts).lower()


def _intent_allowed_by_probes(intent: str, allowed_probes: list[str]) -> bool:
    if intent in {
        "opening",
        "candidate_map",
        "clarify",
        "closing",
        "final_addition",
        "gap_check",
        "baseline",
        "recovery",
        "coverage",
        "await_introduction",
    }:
        return True
    if not allowed_probes:
        return True
    aliases = INTENT_PROBE_ALIASES.get(intent, ())
    blob = " ".join(allowed_probes).lower()
    if intent.replace("_", " ") in blob:
        return True
    return any(alias in blob for alias in aliases)


def validate_generated_question(
    generated: GeneratedQuestion,
    *,
    definition: dict[str, Any] | None,
    policy_competency_id: str | None,
    policy_intent: str,
    policy_depth: int,
    max_depth: int,
    recent_questions: list[str],
    allowed_probes: list[str],
    profile: dict[str, Any] | None = None,
    job_description: str = "",
    resume_text: str = "",
    recent_turns: list[str] | None = None,
) -> ValidationResult:
    reasons: list[str] = []
    question = (generated.question or "").strip()
    if not question:
        reasons.append("empty_question")
    if question.count("?") > 1:
        reasons.append("compound_question")
    lowered = question.lower()
    if any(marker in lowered for marker in PROTECTED_MARKERS):
        reasons.append("protected_topic")

    expected_competency = policy_competency_id
    if expected_competency and generated.competency_id not in {None, "", expected_competency}:
        reasons.append("competency_mismatch")
    if policy_intent and generated.intent not in {policy_intent, "live_question"}:
        # Opening/map can be phrased with nearby intents; still record mismatch for probes.
        if policy_intent not in {"opening", "candidate_map", "await_introduction"}:
            reasons.append("intent_mismatch")
    if generated.depth > max(1, int(max_depth)):
        reasons.append("depth_exceeded")
    if generated.depth > max(1, int(policy_depth) + 1):
        reasons.append("depth_jump")

    if not _intent_allowed_by_probes(policy_intent, allowed_probes):
        reasons.append("probe_intent_not_allowed")

    allowed_ids = _allowed_claim_ids(profile)
    for claim_id in generated.source_claim_ids:
        if allowed_ids and claim_id not in allowed_ids:
            reasons.append("unknown_claim_id")
            break

    current_fp = fingerprint(question)
    for previous in recent_questions[-8:]:
        prev_fp = fingerprint(previous)
        if current_fp and prev_fp and (current_fp == prev_fp or current_fp in prev_fp or prev_fp in current_fp):
            reasons.append("duplicate_question")
            break

    corpus = _grounding_corpus(
        definition=definition,
        profile=profile,
        job_description=job_description,
        resume_text=resume_text,
        recent_turns=list(recent_turns or []),
        competency_id=expected_competency or generated.competency_id,
    )
    for term in UNGROUNDED_TECH_TERMS:
        if term in lowered and term not in corpus:
            reasons.append("ungrounded_term")
            break

    ok = not reasons
    normalized = GeneratedQuestion(
        question=question,
        competency_id=expected_competency or generated.competency_id,
        intent=policy_intent or generated.intent,
        depth=max(1, min(5, int(policy_depth or generated.depth or 1))),
        source_claim_ids=[item for item in generated.source_claim_ids if item in allowed_ids]
        if allowed_ids
        else list(generated.source_claim_ids),
        decision=generated.decision if generated.decision in {"probe", "advance"} else "probe",
    )
    return ValidationResult(ok=ok, question=normalized, reasons=reasons)
