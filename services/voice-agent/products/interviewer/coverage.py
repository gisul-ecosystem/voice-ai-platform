"""Live competency coverage and answer classification."""
from __future__ import annotations

import re
from typing import Any

from products.interviewer.policy import classify_answer_usability

_WS = re.compile(r"\s+")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "establish_context": (
        "situation",
        "when",
        "team",
        "project",
        "role",
        "context",
        "working on",
        "assigned",
        "customer",
        "client",
    ),
    "establish_ownership": (
        "i handled",
        "i led",
        "i built",
        "i owned",
        "i was responsible",
        "my responsibility",
        "i implemented",
        "i ran",
        "i managed",
        "personally",
    ),
    "applied_understanding": (
        "how i",
        "approach",
        "method",
        "process",
        "steps",
        "we used",
        "i used",
        "designed",
        "because",
    ),
    "problem_or_complexity": (
        "difficult",
        "challenge",
        "failed",
        "issue",
        "constraint",
        "risk",
        "blocked",
        "incident",
        "problem",
    ),
    "tradeoff_or_transfer": (
        "tradeoff",
        "trade-off",
        "alternative",
        "instead",
        "would change",
        "next time",
        "learned",
        "chose",
    ),
    "candidate_map": (
        "background",
        "experience",
        "studied",
        "worked",
        "internship",
        "project",
    ),
    "baseline": (
        "example",
        "time when",
        "situation",
    ),
}

DEFAULT_INTENTS = (
    "establish_context",
    "establish_ownership",
    "applied_understanding",
)

EVIDENCE_STATES = frozenset({"missing", "claimed", "demonstrated", "confirmed"})

_NUMBER = re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|%|k|m|b)?\b", re.IGNORECASE)
_QUOTED = re.compile(r"\"([^\"]+)\"|'([^']+)'")
_FIRST_PERSON = re.compile(
    r"\bi\s+(handled|led|built|owned|implemented|designed|wrote|ran|"
    r"managed|reduced|set|rewrote|chose|moved)\s+([^.,;]+)",
    re.IGNORECASE,
)
_OWNERSHIP_CUES = (
    "i handled",
    "i led",
    "i built",
    "i owned",
    "i implemented",
    "i designed",
    "i wrote",
    "i ran",
    "i managed",
    "i reduced",
    "i set",
    "i rewrote",
)
_CONTEXT_CUES = (" when ", " at ", " for the ", " for a ", " with the ", " on the ")
_METHOD_CUES = (" by ", " using ", " steps", " mechanism", " implemented", " designed")
_PROBLEM_CUES = ("failed", "broke", "timeout", "incident", "blocked", "constraint")
_TRADEOFF_CUES = ("instead", "rather than", "trade-off", "tradeoff", "would change")
_WEAK_OBJECTS = frozenset({"it", "that", "this", "them", "things", "stuff"})


def _tokens(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(part) > 2}


def competency_by_id(definition: dict[str, Any] | None, competency_id: str | None) -> dict[str, Any]:
    if not isinstance(definition, dict) or not competency_id:
        return {}
    for item in definition.get("competencies") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == competency_id:
            return item
    return {}


def ladder_steps(definition: dict[str, Any] | None, competency_id: str | None) -> list[dict[str, Any]]:
    if not isinstance(definition, dict) or not competency_id:
        return []
    for item in definition.get("question_ladders") or []:
        if isinstance(item, dict) and str(item.get("competency_id") or "") == competency_id:
            levels = item.get("levels") if isinstance(item.get("levels"), list) else []
            return [step for step in levels if isinstance(step, dict)]
    return []


def required_intents_for(
    definition: dict[str, Any] | None, competency_id: str | None
) -> list[str]:
    competency = competency_by_id(definition, competency_id)
    configured = [
        str(item).strip()
        for item in (competency.get("min_assessment_intents") or [])
        if str(item).strip()
    ]
    if configured:
        return configured
    steps = ladder_steps(definition, competency_id)
    from_ladder = [
        str(step.get("intent") or "").strip()
        for step in steps
        if str(step.get("intent") or "").strip()
    ]
    max_depth = int(competency.get("max_depth") or 4)
    if from_ladder:
        return from_ladder[: max(1, max_depth)]
    return list(DEFAULT_INTENTS[: max(1, min(max_depth, 3))])


def empty_coverage_entry(required: list[str]) -> dict[str, Any]:
    intents = [item for item in required if item]
    return {
        "status": "not_started",
        "required_intents": list(intents),
        "covered_intents": [],
        "missing_intents": list(intents),
        "evidence_ids": [],
        "evidence_states": {intent: "missing" for intent in intents},
    }


def init_coverage(definition: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    if not isinstance(definition, dict):
        return coverage
    for item in definition.get("competencies") or []:
        if not isinstance(item, dict):
            continue
        competency_id = str(item.get("id") or "").strip()
        if not competency_id:
            continue
        coverage[competency_id] = empty_coverage_entry(
            required_intents_for(definition, competency_id)
        )
    return coverage


def _intent_matched(text: str, intent: str) -> bool:
    lowered = (text or "").lower()
    for marker in INTENT_KEYWORDS.get(intent, ()):
        if marker in lowered:
            return True
    slug = intent.replace("_", " ")
    return slug in lowered


def classify_live_answer(
    text: str | None,
    *,
    required_intents: list[str],
    evidence_expected: list[str] | None = None,
    min_words: int = 3,
) -> tuple[str, str, list[str]]:
    """Return (usability, quality, hinted_intents).

    ``hinted_intents`` are keyword matches for debugging only. Callers must
    use ``evidenced_intents`` to update coverage.
    """
    usability = classify_answer_usability(text, min_words=min_words)
    cleaned = _WS.sub(" ", (text or "").strip())
    if usability == "silence":
        return usability, "unusable", []
    if usability == "too_short":
        return usability, "unclear", []
    if usability == "explicit_unknown":
        return usability, "unsupported", []
    if usability != "usable":
        return usability, "unusable", []

    hinted = [intent for intent in required_intents if _intent_matched(cleaned, intent)]
    expected = [item.strip() for item in (evidence_expected or []) if item and item.strip()]
    expected_hits = 0
    blob_tokens = _tokens(cleaned)
    for item in expected:
        needles = _tokens(item)
        if item.lower() in cleaned.lower() or (needles and needles & blob_tokens):
            expected_hits += 1

    if not hinted and expected and expected_hits == 0 and len(cleaned.split()) >= 8:
        return "off_topic", "off_topic", []
    if len(hinted) >= max(1, (len(required_intents) + 1) // 2) and expected_hits >= 1:
        quality = "sufficient"
    elif hinted or expected_hits:
        quality = "partial"
    else:
        quality = "unclear"
    # Keyword hits are a debug hint only — they never complete coverage.
    return "usable", quality, hinted


def extract_evidence_facts(text: str) -> list[str]:
    """Pull concrete facts from an answer: numbers, quotes, first-person verb+object."""
    cleaned = _WS.sub(" ", (text or "").strip())
    if not cleaned:
        return []
    facts: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        item = value.strip()
        key = item.lower()
        if not item or key in seen or key in _WEAK_OBJECTS:
            return
        seen.add(key)
        facts.append(item)

    for number in _NUMBER.findall(cleaned):
        _add(number)
    for group in _QUOTED.findall(cleaned):
        quoted = next((part.strip() for part in group if part and part.strip()), "")
        if quoted:
            _add(quoted)
    for match in _FIRST_PERSON.finditer(cleaned):
        obj = match.group(2).strip()
        head = obj.split()[0].lower() if obj else ""
        if len(obj) >= 4 and head not in _WEAK_OBJECTS:
            _add(f"I {match.group(1).lower()} {obj}")
    return facts[:8]


def _fact_maps_to_evidence(fact: str, evidence_expected: list[str]) -> bool:
    fact_tokens = _tokens(fact)
    if not fact_tokens:
        return False
    for item in evidence_expected:
        needles = _tokens(item)
        if needles and needles & fact_tokens:
            return True
    return False


def _intent_has_concrete_evidence(intent: str, text: str, facts: list[str]) -> bool:
    if not facts:
        return False
    lowered = f" {(text or '').lower()} "
    if intent == "establish_ownership":
        return any(cue in lowered for cue in _OWNERSHIP_CUES)
    if intent == "establish_context":
        return any(cue in lowered for cue in _CONTEXT_CUES)
    if intent == "applied_understanding":
        return any(cue in lowered for cue in _METHOD_CUES)
    if intent == "problem_or_complexity":
        return any(cue in lowered for cue in _PROBLEM_CUES)
    if intent == "tradeoff_or_transfer":
        return any(cue in lowered for cue in _TRADEOFF_CUES)
    return False


def evidenced_intents(
    *,
    required_intents: list[str],
    evidence_expected: list[str] | None = None,
    answer_eval: Any | None = None,
    asked_intent: str | None = None,
    answer_text: str | None = None,
) -> list[str]:
    """Intents covered by evidenced facts or a prior evaluation — never keywords alone."""
    required = [item for item in required_intents if item]
    if not required:
        return []
    if answer_eval is not None and getattr(answer_eval, "factually_correct", True) is False:
        return []
    substance = str(getattr(answer_eval, "technical_substance", "") or "").strip()
    if substance in {"surface", "incorrect", "not_applicable"}:
        return []

    eval_facts = [
        str(item).strip()
        for item in (getattr(answer_eval, "key_facts_stated", None) or [])
        if str(item).strip()
    ] if answer_eval is not None else []
    extracted = extract_evidence_facts(answer_text or "")
    facts = list(dict.fromkeys([*eval_facts, *extracted]))
    expected = [item.strip() for item in (evidence_expected or []) if item and item.strip()]
    eval_ok = bool(
        answer_eval is not None
        and substance in {"deep", "partial"}
        and (
            getattr(answer_eval, "matches_evidence_expected", False)
            or eval_facts
            or any(_fact_maps_to_evidence(fact, expected) for fact in facts)
        )
    )
    if not facts and not eval_ok:
        return []

    target = asked_intent if asked_intent in required else None
    if target:
        if eval_ok or _intent_has_concrete_evidence(target, answer_text or "", facts):
            return [target]
        return []
    return [
        intent
        for intent in required
        if _intent_has_concrete_evidence(intent, answer_text or "", facts)
    ]


def quality_from_evaluation(answer_eval: Any) -> str | None:
    """Map an LLM substance verdict onto the live quality vocabulary.

    See the score-mapping threshold table in AnswerEvaluation's docstring
    (validator.py) for the full deep/partial/surface -> quality mapping.

    Returns None when the verdict is absent or non-committal, so the caller keeps
    the keyword heuristic from ``classify_live_answer``.
    """
    # A factually wrong claim caps quality regardless of how deep it sounds.
    if getattr(answer_eval, "factually_correct", True) is False:
        return "unclear"
    substance = str(getattr(answer_eval, "technical_substance", "") or "").strip()
    if substance == "deep":
        return "sufficient"
    if substance == "partial":
        return "partial"
    if substance in {"surface", "incorrect"}:
        return "unclear"
    return None


def apply_coverage(
    coverage: dict[str, dict[str, Any]],
    *,
    competency_id: str | None,
    covered_intents: list[str],
    evidence_id: str | None = None,
    answer_eval: Any | None = None,
) -> dict[str, dict[str, Any]]:
    if not competency_id or competency_id not in coverage:
        return coverage
    entry = dict(coverage[competency_id])
    required = list(entry.get("required_intents") or [])
    already = list(entry.get("covered_intents") or [])
    for intent in covered_intents:
        if intent in required and intent not in already:
            already.append(intent)
    missing = [intent for intent in required if intent not in already]
    evidence_ids = list(entry.get("evidence_ids") or [])
    evidence_states = {
        intent: state
        for intent, state in (entry.get("evidence_states") or {}).items()
        if intent in required and state in EVIDENCE_STATES
    }
    for intent in required:
        evidence_states.setdefault(intent, "missing")
    if evidence_id and evidence_id not in evidence_ids:
        evidence_ids.append(evidence_id)
    for intent in covered_intents:
        if intent not in required:
            continue
        previous = evidence_states.get(intent, "missing")
        evidence_states[intent] = "confirmed" if previous == "demonstrated" else "demonstrated"
    if not already:
        status = "not_started"
    elif missing:
        status = "partial"
    else:
        status = "complete"
    if already and not missing and not evidence_ids:
        status = "insufficient_evidence"
    # A named-but-hollow answer must never close out a competency.
    if status == "complete" and quality_from_evaluation(answer_eval) == "unclear":
        status = "insufficient_evidence"
    coverage[competency_id] = {
        "status": status,
        "required_intents": required,
        "covered_intents": already,
        "missing_intents": missing,
        "evidence_ids": evidence_ids,
        "evidence_states": evidence_states,
    }
    return coverage


def first_incomplete_competency(
    coverage: dict[str, dict[str, Any]],
    competency_ids: list[str],
) -> str | None:
    for competency_id in competency_ids:
        entry = coverage.get(competency_id) or {}
        if entry.get("missing_intents"):
            return competency_id
    return None
