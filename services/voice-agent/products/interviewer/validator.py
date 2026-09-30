"""Validate generated interview questions before they are spoken."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from products.interviewer.coverage import competency_by_id, ladder_steps

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|%|k|m|b)?\b", re.IGNORECASE)
_QUOTED = re.compile(r"\"([^\"]+)\"|'([^']+)'")
_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b")

HOOK_STOPWORDS = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "have",
        "been",
        "were",
        "they",
        "them",
        "then",
        "when",
        "what",
        "which",
        "into",
        "just",
        "also",
        "very",
        "used",
        "using",
        "work",
        "worked",
        "working",
        "about",
        "your",
        "their",
        "there",
        "than",
        "some",
        "more",
        "only",
        "would",
        "could",
        "should",
        "problem",
        "thing",
        "stuff",
        "time",
        "role",
        "please",
        "briefly",
        "recent",
        # Weak trailing fillers that produced "You mentioned safely/overall".
        "overall",
        "safely",
        "really",
        "basically",
        "actually",
        "fine",
        "good",
        "okay",
        "yeah",
        "sure",
        "main",
        "mode",
        "mentioned",
        "operators",
        "replay",
        # Function words — without these, token windows became "One deal was" /
        # "the commercial" mid-phrase fragments (sales dry-run).
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "for",
        "to",
        "of",
        "on",
        "in",
        "at",
        "by",
        "as",
        "it",
        "its",
        "my",
        "our",
        "his",
        "her",
        "one",
        "two",
        "any",
        "all",
        "each",
        "every",
        "such",
        "deal",  # too generic alone; prefer "manufacturing customer" etc.
    }
)

_TECH_HOOK_PHRASES = (
    "dead-letter queue",
    "dead letter queue",
    "exponential backoff",
    "idempotency keys",
    "idempotency key",
    "webhook storms",
    "webhook storm",
    "rate limiting",
    "rate-limited",
    "payment intents",
    "p95 latency",
)

_TECH_HOOK_TOKENS = frozenset(
    {
        "redis",
        "fastapi",
        "postgres",
        "postgresql",
        "kafka",
        "rabbitmq",
        "kubernetes",
        "docker",
        "graphql",
        "grpc",
        "mongodb",
        "dynamodb",
        "payments",
        "webhooks",
        "webhook",
        "backoff",
        "idempotency",
        "graph",
    }
)

_HOOK_VERBS = frozenset(
    {
        "migrated",
        "worked",
        "built",
        "owned",
        "handled",
        "implemented",
        "designed",
        "added",
        "used",
        "measured",
        "solved",
        "solve",
        "backend",
        "engineer",
        "who",
        "after",
        "before",
        "during",
        # Copulas / light verbs that left bare fragments when stripped partially.
        "was",
        "is",
        "are",
        "were",
        "be",
        "being",
        "am",
        "had",
        "has",
        "did",
        "do",
        "does",
        "got",
        "get",
        "made",
        "make",
        "said",
        "say",
        "went",
        "go",
        "came",
        "come",
        "took",
        "take",
        "ran",
        "run",
        "saw",
        "see",
        "knew",
        "know",
        "gave",
        "give",
        "told",
        "tell",
        "asked",
        "ask",
        "tried",
        "try",
        "needed",
        "need",
        "wanted",
        "want",
        "seemed",
        "seem",
        "became",
        "become",
        "started",
        "start",
        "ended",
        "end",
        "closed",
        "close",
        "negotiated",
        "negotiate",
    }
)

# Hard-block reasons cause a full LLM retry (never a template string).


SKIP_HOOK_INTENTS = frozenset(
    {
        "opening",
        "candidate_map",
        "clarify",
        "closing",
        "final_addition",
        "await_introduction",
    }
)

PROBE_SHAPE_ROTATION = ("why", "failure_mode", "metric", "trade_off")

TRIVIA_MARKERS = (
    "brain teaser",
    "riddle",
    "puzzle",
    "what does sql stand for",
    "what does api stand for",
    "what does http stand for",
    "full form of",
    "expand the acronym",
    "what is the full form",
    "define polymorphism in one sentence",
    "write a linked list from scratch",
)

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

TRIVIA_MARKERS = (
    "brain teaser",
    "brain-teaser",
    "riddle",
    "puzzle",
)

# Only these justify discarding the model's question. Everything else is a
# quality note: worth a repair retry and worth logging, but a slightly imperfect
# real question beats a canned one that ignores what the candidate just said.
HARD_BLOCK_REASONS: frozenset[str] = frozenset(
    (
        "empty_question",
        "protected_topic",
        "duplicate_question",
        "project_in_competency_question",
        "generic_parrot_question",
        "generic_learning_question",
        "competency_mismatch",
        "section_violation",
    )
)


def is_speakable(reasons: list[str]) -> bool:
    """True when the question may be spoken despite failing validation."""
    return not any(reason in HARD_BLOCK_REASONS for reason in reasons)


UNGROUNDED_TECH_TERMS = TECH_TERMS = (
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

KNOWN_INTENTS = frozenset(
    set(INTENT_PROBE_ALIASES)
    | {
        "closing",
        "await_introduction",
        "coverage",
        "consistency_check",
        "evidence_gap_stop",
        "resume_project",
    }
)

BLOCKING_REASONS = frozenset(
    {
        "empty_question",
        "compound_question",
        "protected_topic",
        "competency_label_spoken",
        "duplicate_question",
        "repeated_question_frame",
        "adjacent_near_duplicate",
        "project_in_competency_question",
        "competency_mismatch",
        "section_violation",
        "generic_parrot_question",
        "generic_learning_question",
        "trivia_question",
        "non_job_trivia",
        "ungrounded_term",
        "resume_project_ungrounded",
        "invalid_hook_phrase",
    }
)

_ACTION_TO_INTENT = {
    "PROBE_FOR_CONTEXT": "establish_context",
    "PROBE_FOR_OWNERSHIP": "establish_ownership",
    "PROBE_FOR_METHOD": "applied_understanding",
    "PROBE_FOR_REASONING": "problem_or_complexity",
    "PROBE_FOR_RESULT": "problem_or_complexity",
    "PROBE_FOR_REFLECTION": "tradeoff_or_transfer",
    "ASK_BASELINE": "establish_context",
}


def canonical_intent(intent: str | None) -> str:
    """Normalize policy/action labels to ladder assessment intents."""
    value = (intent or "").strip()
    if value == "baseline":
        return "establish_context"
    return _ACTION_TO_INTENT.get(value, value)



TechnicalSubstance = Literal[
    "surface", "partial", "deep", "incorrect", "not_applicable"
]

SUBSTANCE_VALUES: frozenset[str] = frozenset(
    ("surface", "partial", "deep", "incorrect", "not_applicable")
)

# Informational only — the numeric depth ladder in policy.py stays authoritative.
DEPTH_TAG_VALUES: frozenset[str] = frozenset(("concept", "applied", "trade_off"))
PROBE_SHAPE_VALUES: frozenset[str] = frozenset(
    ("why", "trade_off", "failure_mode", "metric", "other")
)


@dataclass
class AnswerEvaluation:
    """LLM verdict on the candidate's previous answer, returned with the next question.

    Contract:
      technical_substance: "surface" | "partial" | "deep" | "incorrect" | "not_applicable"
        - deep: specific, verifiable detail (numbers, mechanisms, trade-offs, decisions).
        - partial: practical application shown but missing concrete trade-offs/metrics.
        - surface: only names concepts / textbook definition, no applied evidence.
        - incorrect: legacy value, kept for backward compatibility — prefer combining
          a depth value with factually_correct=False for new evaluations.
        - not_applicable: greeting, meta-question, or non-technical turn.
      factually_correct: independent of depth — false whenever the answer contains a
        claim that contradicts established fact for this domain, even if the answer is
        otherwise deep or partial. A "deep but wrong" answer is a distinct, more
        important signal than a shallow one and must not be hidden by the depth label.
        True (default) when no claim is factually wrong, including surface/not_applicable
        answers that make no verifiable claim at all.
      key_facts_stated: concrete facts extracted from the answer, reused across turns so
        the interviewer does not re-ask what is already known.
      reasoning: one sentence, written so a human reviewer could paste it directly into
        the scorecard as justification.
      matches_evidence_expected: whether the answer satisfies the competency's
        evidence_expected list.
      needs_clarification: true only when the answer itself is too ambiguous to score
        confidently (unclear pronouns, contradictions, cut-off sentences) — distinct
        from "surface", which means a clear but shallow answer.
      
      Phase 4 — Belief Judge fields:
      credibility_assessment: "believable" | "questionable" | "likely_fabricated"
        - believable: consistent details, specific context, reasonable scope claims
        - questionable: vague details, inconsistencies, or overly broad claims that need verification  
        - likely_fabricated: clear signs of fabrication (impossible claims, textbook parroting, contradictions)
      credibility_signals: list of specific patterns that influenced the credibility assessment
        e.g. ["vague_ownership", "unrealistic_scale", "buzzword_heavy", "missing_context"]

    Score-mapping threshold (single source of truth other modules reference):
      factually_correct == False -> unclear -> weak, regardless of technical_substance.
      Otherwise, technical_substance -> coverage quality (coverage.quality_from_evaluation)
                                     -> scorecard strength (scoring._strength_from_evaluation)
        deep               -> sufficient  -> strong
        partial            -> partial     -> sufficient
        surface/incorrect  -> unclear      -> weak
        not_applicable     -> None (falls back to the keyword/word-count heuristic)
    """

    technical_substance: TechnicalSubstance = "not_applicable"
    key_facts_stated: list[str] = field(default_factory=list)
    reasoning: str = ""
    matches_evidence_expected: bool = False
    needs_clarification: bool = False
    factually_correct: bool = True
    slots_demonstrated: list[str] = field(default_factory=list)
    slots_claimed: list[str] = field(default_factory=list)
    contradicts_earlier: bool = False
    # Phase 4: Belief Judge fields
    credibility_assessment: str = "believable"  # "believable" | "questionable" | "likely_fabricated" 
    credibility_signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "technical_substance": self.technical_substance,
            "key_facts_stated": list(self.key_facts_stated),
            "reasoning": self.reasoning,
            "matches_evidence_expected": self.matches_evidence_expected,
            "needs_clarification": self.needs_clarification,
            "factually_correct": self.factually_correct,
            "slots_demonstrated": list(self.slots_demonstrated),
            "slots_claimed": list(self.slots_claimed),
            "contradicts_earlier": self.contradicts_earlier,
            # Phase 4: Belief Judge fields
            "credibility_assessment": self.credibility_assessment,
            "credibility_signals": list(self.credibility_signals),
        }


def parse_answer_evaluation(payload: Any) -> AnswerEvaluation | None:
    """Return a validated evaluation, or None so callers fall back to heuristics."""
    if not isinstance(payload, dict):
        return None
    substance = str(payload.get("technical_substance") or "").strip().lower()
    if substance not in SUBSTANCE_VALUES:
        return None
    raw_facts = payload.get("key_facts_stated")
    facts = (
        [str(item).strip() for item in raw_facts if str(item).strip()]
        if isinstance(raw_facts, list)
        else []
    )
    valid_slots = {
        "ownership",
        "approach",
        "mechanism",
        "complexity_or_cost",
        "tradeoff",
        "failure_mode",
        "optimization",
        "measurement",
    }

    def slots(key: str) -> list[str]:
        raw = payload.get(key)
        if not isinstance(raw, list):
            return []
        return [
            str(item).strip().lower()
            for item in raw
            if str(item).strip().lower() in valid_slots
        ]

    # Phase 4: Parse Belief Judge fields
    credibility = str(payload.get("credibility_assessment") or "believable").strip().lower()
    if credibility not in {"believable", "questionable", "likely_fabricated"}:
        credibility = "believable"
    
    credibility_signals_raw = payload.get("credibility_signals")
    credibility_signals = (
        [str(item).strip() for item in credibility_signals_raw if str(item).strip()]
        if isinstance(credibility_signals_raw, list)
        else []
    )

    return AnswerEvaluation(
        technical_substance=substance,  # type: ignore[arg-type]
        key_facts_stated=facts[:20],
        reasoning=str(payload.get("reasoning") or "").strip()[:500],
        matches_evidence_expected=bool(payload.get("matches_evidence_expected")),
        needs_clarification=bool(payload.get("needs_clarification")),
        factually_correct=bool(payload.get("factually_correct", True)),
        slots_demonstrated=slots("slots_demonstrated"),
        slots_claimed=slots("slots_claimed"),
        contradicts_earlier=bool(payload.get("contradicts_earlier")),
        # Phase 4: Belief Judge fields
        credibility_assessment=credibility,
        credibility_signals=credibility_signals[:10],  # Limit to 10 signals
    )


@dataclass
class GeneratedQuestion:
    question: str
    competency_id: str | None = None
    intent: str = "live_question"
    depth: int = 1
    source_claim_ids: list[str] = field(default_factory=list)
    decision: str = "probe"
    answer_evaluation: AnswerEvaluation | None = None
    depth_tag: str | None = None
    probe_shape: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    question: GeneratedQuestion
    reasons: list[str] = field(default_factory=list)


def fingerprint(text: str) -> str:
    cleaned = _PUNCT.sub(" ", (text or "").lower())
    return _WS.sub(" ", cleaned).strip()


def hook_stem_tokens(text: str) -> list[str]:
    """Content stems from a hook phrase — aligned with extract_hook_fact filtering.

    Multi-word hooks (e.g. ``commercial negotiation``) yield multiple stems; the
    spoken question must include at least one. Function words and light verbs are
    never stems, so a fragment like ``One deal was`` does not silently pass.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _NUMBER.findall(text or ""):
        token = match.lower()
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    for token in fingerprint(text).split():
        if (
            len(token) < 4
            or token in HOOK_STOPWORDS
            or token in _HOOK_VERBS
            or token in seen
        ):
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def is_clean_hook_fact(hook: str) -> bool:
    """True when hook matches extract_hook_fact's success criterion.

    Accepts ≥2 content tokens, a single tech token, a metric/number, or empty
    (no hook). Rejects mid-phrase fragments like ``One deal was`` / ``the commercial``.
    """
    text = (hook or "").strip()
    if not text:
        return True
    if _NUMBER.fullmatch(text):
        return True
    lowered = text.lower()
    if any(phrase == lowered or phrase in lowered for phrase in _TECH_HOOK_PHRASES):
        return True
    content = _content_hook_tokens(text)
    if len(content) >= 2:
        return True
    if len(content) == 1 and content[0].lower() in _TECH_HOOK_TOKENS:
        return True
    if len(content) == 1 and _NUMBER.search(content[0]):
        return True
    return False


def _content_hook_tokens(candidate: str) -> list[str]:
    """Drop function words / light verbs from a candidate span."""
    return [
        tok
        for tok in candidate.split()
        if tok.lower() not in HOOK_STOPWORDS and tok.lower() not in _HOOK_VERBS
    ]


def extract_hook_fact(text: str) -> str:
    """Pick a concrete entity/tech noun from the answer — never a trailing filler."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for phrase in _TECH_HOOK_PHRASES:
        if phrase in lowered:
            start = lowered.find(phrase)
            return cleaned[start : start + len(phrase)]
    numbers = _NUMBER.findall(cleaned)
    if numbers:
        return numbers[0]
    quoted = _QUOTED.findall(cleaned)
    for group in quoted:
        value = next((item.strip() for item in group if item and item.strip()), "")
        if value:
            return value
    words = _WORD.findall(cleaned)
    for word in words:
        if word.lower() in _TECH_HOOK_TOKENS:
            return word
    # Scan every 2–3 word window; skip spans that collapse to mid-phrase fragments
    # after stripping function words (e.g. "One deal was" → empty / "deal").
    # Advance one character on reject so a discarded window does not hide the
    # next overlapping noun phrase ("owned the commercial" must not block
    # "commercial negotiation").
    phrase_re = re.compile(
        r"\b([A-Za-z][A-Za-z0-9_+#-]{2,}(?:\s+[A-Za-z][A-Za-z0-9_+#-]{2,}){1,2})\b"
    )
    pos = 0
    while pos < len(cleaned):
        phrase_match = phrase_re.search(cleaned, pos)
        if not phrase_match:
            break
        tokens = _content_hook_tokens(phrase_match.group(1).strip())
        if len(tokens) >= 2:
            return " ".join(tokens[:3])
        if len(tokens) == 1 and tokens[0].lower() in _TECH_HOOK_TOKENS:
            return tokens[0]
        pos = phrase_match.start() + 1
    significant = [
        word
        for word in words
        if word.lower() not in HOOK_STOPWORDS and word.lower() not in _HOOK_VERBS
    ]
    for index, word in enumerate(significant):
        if index > 0 and word[0].isupper():
            return word
    # Prefer a longer content noun over a short leftover like "deal".
    if significant:
        ranked = sorted(significant, key=lambda w: len(w), reverse=True)
        return ranked[0]
    return ""


def prefix_tokens(text: str, count: int = 6) -> list[str]:
    tokens = fingerprint(text).split()
    return tokens[:count]


def next_probe_shape(last_shape: str | None) -> str:
    rotation = list(PROBE_SHAPE_ROTATION)
    if last_shape in rotation:
        return rotation[(rotation.index(last_shape) + 1) % len(rotation)]
    return rotation[0]


def _question_tokens(text: str) -> set[str]:
    ignored = {
        "can", "could", "would", "you", "your", "the", "about", "me",
        "please", "briefly", "recent", "work", "worked",
    }
    synonyms = {
        "describe": "explain",
        "discuss": "explain",
        "share": "explain",
        "tell": "explain",
        "walk": "explain",
        "overview": "explain",
    }
    return {
        synonyms.get(token, token)
        for token in fingerprint(text).split()
        if len(token) > 2 and token not in ignored
    }


def _grounding_terms(text: str) -> set[str]:
    stopwords = {
        "about", "after", "because", "could", "did", "from", "have", "into",
        "that", "their", "them", "they", "this", "what", "when", "where",
        "which", "while", "with", "would", "your", "used", "using", "work",
        "worked", "project", "specific", "technical", "problem", "result",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 3 and token not in stopwords
    }


def _near_duplicate(left: str, right: str, threshold: float = 0.7) -> bool:
    left_tokens = _question_tokens(left)
    right_tokens = _question_tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap / min(len(left_tokens), len(right_tokens)) >= threshold


def _same_question_frame(left: str, right: str) -> bool:
    """Return True if left and right share the same opening question frame/stem."""
    p_left = prefix_tokens(left, count=5)
    p_right = prefix_tokens(right, count=5)
    if len(p_left) >= 4 and len(p_right) >= 4:
        # Match common frames like "can you describe the specific"
        if p_left[:4] == p_right[:4]:
            return True
        overlap = len(set(p_left[:5]) & set(p_right[:5]))
        if overlap >= 4:
            return True
    return False


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
    depth_tag = str(payload.get("depth_tag") or "").strip().lower() or None
    if depth_tag not in DEPTH_TAG_VALUES:
        depth_tag = None
    probe_shape = str(payload.get("probe_shape") or "").strip().lower() or None
    if probe_shape not in PROBE_SHAPE_VALUES:
        probe_shape = None
    return GeneratedQuestion(
        question=question,
        competency_id=competency_id,
        intent=str(payload.get("intent") or "live_question").strip() or "live_question",
        depth=max(1, min(5, depth)),
        source_claim_ids=claim_ids,
        decision=str(payload.get("decision") or "probe").strip().lower() or "probe",
        answer_evaluation=parse_answer_evaluation(payload.get("answer_evaluation")),
        depth_tag=depth_tag,
        probe_shape=probe_shape,
    )


def ladder_fallback_question(
    definition: dict[str, Any] | None,
    *,
    competency_id: str | None,
    intent: str,
    last_candidate_turn: str | None = None,
) -> str:
    candidate = " ".join((last_candidate_turn or "").split()).strip()
    if candidate and intent in {"candidate_map", "await_introduction"}:
        return (
            "Thanks for sharing that. Which project or experience would you like "
            "to use as the main example for this interview?"
        )
    if candidate and intent in {
        "establish_context",
        "baseline",
        "candidate_map",
        "gap_check",
    }:
        return (
            "You mentioned "
            f"{candidate[:180].rstrip('.!?')}. "
            "What specific problem were you solving, and what did you personally do?"
        )
    for step in ladder_steps(definition, competency_id):
        if str(step.get("intent") or "").strip() == intent:
            example = str(step.get("example_question") or "").strip()
            if example:
                return example
    defaults = {
        "establish_context": "Can you briefly describe the situation?",
        "establish_ownership": "What part of that did you personally handle?",
        "applied_understanding": "How did you approach that work?",
        "problem_or_complexity": "What was difficult about that?",
        "tradeoff_or_transfer": "Looking back, what would you change?",
        "gap_check": "Can you share one concrete example from that work?",
        "candidate_map": "Please share a short overview of the work most relevant to this role.",
        "opening": (
            "Thanks for joining. I'm your interviewer for this conversation. "
            "To get started, please introduce yourself — a short overview of your "
            "background, and the work that is most relevant to this role."
        ),
        "clarify": "Please continue — tell me a bit more about that.",
        "final_addition": "Before we close, is there one example you would still like to add?",
    }
    return defaults.get(
        intent,
        "Can you share one concrete example from that work?",
    )


def _compatible_intents(expected: str, generated: str) -> bool:
    if expected == generated:
        return True
    families = (
        {"candidate_map", "await_introduction", "baseline", "establish_context"},
        {"establish_ownership", "applied_understanding"},
        {"problem_or_complexity", "tradeoff_or_transfer"},
    )
    return any(expected in family and generated in family for family in families)


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
    comp_name = str(competency.get("name") or "").lower()
    comp_def = str(competency.get("definition") or "").lower()
    parts.append(comp_name)
    parts.append(comp_def)
    if any(k in comp_name or k in comp_def for k in ("sql", "database", "postgres", "mysql", "data")):
        parts.append("index query table schema join transaction deadlock postgres postgresql sharding")
    if any(k in comp_name or k in comp_def for k in ("backend", "system", "infrastructure", "devops", "cloud", "api")):
        parts.append("api service queue latency timeout cache redis kafka microservice websocket http client")
    if any(k in comp_name or k in comp_def for k in ("dsa", "algorithm", "data structure", "problem solving")):
        parts.append("tree graph array string map queue stack complexity latency deadlock")
    if any(k in comp_name or k in comp_def for k in ("python", "java", "golang", "programming", "code", "development")):
        parts.append("api schema queue timeout deadlock index latency http client")
    if isinstance(profile, dict):
        for item in profile.get("claims") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("value") or ""))
    corpus = " ".join(parts).lower()
    if "worker pool" in corpus or "ingestion" in corpus:
        parts.append("queue")
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



def looks_like_compound_question(text: str) -> bool:
    """Return True if the text asks two questions in one response."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    # If there are 2 or more question marks, it's definitely compound
    if cleaned.count("?") >= 2:
        return True
    lowered = cleaned.lower()
    # Check for conjunction joining two ask clauses with single question mark
    # e.g., "... and if you...", "... and how did you...", "... and what happened..."
    compound_patterns = (
        r",\s*and\s+(?:how|what|why|did|could|would|if|where|when)\b",
        r"\band\s+if\s+you\b",
        r"\band\s+how\s+did\s+you\b",
        r"\band\s+what\s+(?:happened|did|was|were)\b",
    )
    for pat in compound_patterns:
        if re.search(pat, lowered):
            return True
    return False


def _looks_like_non_job_trivia(question: str, *, corpus: str) -> bool:
    """Block puzzles/acronym drills unless clearly applied to the candidate's work."""
    lowered = (question or "").lower()
    if not lowered:
        return False
    applied = any(
        token in lowered
        for token in (
            "how did you",
            "in your",
            "when you",
            "on the job",
            "in production",
            "in your project",
            "at work",
        )
    )
    if any(marker in lowered for marker in TRIVIA_MARKERS):
        return not applied
    if "stand for" in lowered or "full form" in lowered:
        return not applied
    _ = corpus  # reserved for future job-critical allow-lists
    return False


def _is_generic_parrot_question(lowered: str) -> bool:
    if re.search(r"\bregarding\b", lowered) and re.search(
        r"\btell me more\b|\bcan you tell me\b", lowered
    ):
        return True
    if "concrete example from that work" in lowered:
        return True
    if re.search(r"\btell me more about (this|that|it)\b", lowered):
        return True
    return False


# Phrases that produce generic "what did you learn?" questions — never acceptable
# as standalone competency questions unless the competency is literally about learning habits.
_LEARNING_FALLBACK_PHRASES = (
    "what did you learn",
    "what was your learning",
    "learning experience",
    "what did you gain from",
    "what did you take away",
    "what was your takeaway",
    "technical approach to learning",
    "what have you learned",
    "what lessons did you",
    "what did this teach you",
)

# Competency names where "learning" is a real technical term — do not block for these.
_TECHNICAL_LEARNING_COMPETENCIES = frozenset({
    "machine learning", "deep learning", "reinforcement learning",
    "transfer learning", "federated learning", "meta-learning",
    "online learning", "active learning",
})


def speaks_competency_label(question: str, competency_name: str) -> bool:
    """True when the question speaks the admin rubric competency name verbatim as a noun phrase."""
    q_low = (question or "").lower()
    name_low = (competency_name or "").strip().lower()
    if not name_low or len(name_low) < 3:
        return False
    # If the name is multiple words like 'Role expertise', check exact phrase match
    pattern = rf"\b{re.escape(name_low)}\b"
    if re.search(pattern, q_low):
        return True
    return False


def _is_generic_learning_question(lowered: str, *, policy_competency_id: str | None = None,
                                   policy_intent: str | None = None) -> bool:
    """Return True when the question is a generic learning/growth fallback.

    Never fires when:
    - The competency is a legitimate ML/DL competency (learning IS the topic).
    - The intent is opening/candidate_map (background questions are fine there).
    """
    # Only block during competency assessment turns.
    if (policy_intent or "") in {
        "opening", "candidate_map", "await_introduction", "baseline",
        "clarify", "final_addition", "gap_check", "closing",
    }:
        return False
    # If the competency name is a real technical learning domain, allow it.
    competency_blob = (policy_competency_id or "").lower().replace("_", " ")
    if any(term in competency_blob for term in _TECHNICAL_LEARNING_COMPETENCIES):
        return False
    return any(phrase in lowered for phrase in _LEARNING_FALLBACK_PHRASES)


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
    resume_focus: str = "",
    resume_projects: list[str] | None = None,
    require_resume_grounding: bool = False,
    hook_fact: str | None = None,
    required_probe_shape: str | None = None,
    last_probe_shape: str | None = None,
) -> ValidationResult:
    reasons: list[str] = []
    # Policy owns intent; action/label aliases must not reject a good spoken question.
    policy_intent = canonical_intent(policy_intent)
    question = (generated.question or "").strip()
    if not question:
        reasons.append("empty_question")
    if looks_like_compound_question(question):
        reasons.append("compound_question")
    lowered = question.lower()
    if (
        re.match(r"^\s*(?:so\s+)?you\b", lowered)
        and (lowered.endswith("?") or "right" in lowered)
    ) or re.search(r",\s*(?:right|is that correct)\??\s*$", lowered):
        reasons.append("leading_question")
    if any(marker in lowered for marker in PROTECTED_MARKERS):
        reasons.append("protected_topic")
    if any(marker in lowered for marker in TRIVIA_MARKERS):
        reasons.append("trivia_question")
    if _is_generic_parrot_question(lowered):
        reasons.append("generic_parrot_question")
    if _is_generic_learning_question(
        lowered,
        policy_competency_id=policy_competency_id,
        policy_intent=policy_intent,
    ):
        reasons.append("generic_learning_question")
    live_probe = (policy_intent or "") not in SKIP_HOOK_INTENTS
    if hook_fact and not is_clean_hook_fact(hook_fact):
        reasons.append("invalid_hook_phrase")
    # Hook details and probe-shape rotation guide wording, but do not reject a
    # question that is otherwise safe, grounded, policy-compatible, and unique.

    expected_competency = (policy_competency_id or "").strip().lower()
    gen_comp = (generated.competency_id or "").strip().lower()
    if definition and isinstance(definition.get("competencies"), list):
        for comp in definition["competencies"]:
            c_name = str(comp.get("name") or "")
            if speaks_competency_label(question, c_name):
                reasons.append("competency_label_spoken")
                break
    if expected_competency and gen_comp and gen_comp != expected_competency:
        expected_tokens = set(re.findall(r"[a-z0-9]+", expected_competency))
        gen_tokens = set(re.findall(r"[a-z0-9]+", gen_comp))
        if not (expected_tokens & gen_tokens):
            reasons.append("competency_mismatch")
    project_intents = {
        "resume_project",
        "opening",
        "candidate_map",
        "await_introduction",
        "baseline",
    }
    in_project_phase = (policy_intent or "") in project_intents
    if not in_project_phase:
        # Competency section: any question that names a resume project is a section violation.
        _GENERIC_TECH_WORDS = frozenset({
            "project", "projects", "pipeline", "pipelines", "model", "models",
            "service", "services", "system", "systems", "data", "app", "application",
            "web", "database", "api", "apis", "code", "tool", "tools", "platform",
            "learning", "python", "backend", "frontend", "server", "cloud",
            "feature", "features", "module", "modules", "process", "interface",
        })
        names = [str(resume_focus).strip()] if resume_focus else []
        names.extend(str(item).strip() for item in (resume_projects or []) if str(item).strip())
        for name in names:
            clean_name = name.strip()
            if len(clean_name) > 3 and clean_name.lower() not in _GENERIC_TECH_WORDS:
                pattern = rf"\b{re.escape(clean_name.lower())}\b"
                if re.search(pattern, lowered):
                    reasons.append("project_in_competency_question")
                    reasons.append("competency_mismatch")
                    reasons.append("section_violation")
                    break
    if in_project_phase and require_resume_grounding:
        # Project section: a question that drifts to a different named competency
        # (e.g. starts a DSA puzzle mid-project) is also a section violation.
        drift_markers = (
            "data structure", "algorithm", "time complexity", "space complexity",
            "big o", "leetcode", "sorting", "binary search", "graph", "tree",
            "sql query", "join", "index", "normaliz",
        )
        if any(marker in lowered for marker in drift_markers) and not (
            resume_focus and resume_focus.lower() in lowered
        ):
            reasons.append("section_violation")
    # The policy owns the assessment intent. The model's intent tag is metadata
    # and must not reject otherwise safe, grounded wording.
    if generated.depth > max(1, int(max_depth)):
        reasons.append("depth_exceeded")
    if generated.depth > max(1, int(policy_depth) + 1):
        reasons.append("depth_jump")

    allowed_ids = _allowed_claim_ids(profile)
    for claim_id in generated.source_claim_ids:
        if allowed_ids and claim_id not in allowed_ids:
            reasons.append("unknown_claim_id")
            break

    current_fp = fingerprint(question)
    for previous in recent_questions[-8:]:
        prev_fp = fingerprint(previous)
        if current_fp and prev_fp and (
            current_fp == prev_fp
            or current_fp in prev_fp
            or prev_fp in current_fp
            or _near_duplicate(current_fp, prev_fp)
        ):
            reasons.append("duplicate_question")
            break

    # Adjacent same-frame / soft near-dup: catches "Can you describe the specific
    # actions…" → "Can you describe the specific steps…" which the 0.7 Jaccard miss.
    if recent_questions and live_probe:
        previous = recent_questions[-1]
        prev_fp = fingerprint(previous)
        if _same_question_frame(question, previous):
            reasons.append("repeated_question_frame")
        elif current_fp and prev_fp and _near_duplicate(
            current_fp, prev_fp, threshold=0.45
        ):
            reasons.append("adjacent_near_duplicate")

    corpus = _grounding_corpus(
        definition=definition,
        profile=profile,
        job_description=job_description,
        resume_text=resume_text,
        recent_turns=list(recent_turns or []),
        competency_id=expected_competency or generated.competency_id,
    )
    if require_resume_grounding and resume_text:
        resume_terms = _grounding_terms(
            f"{resume_focus} {resume_text} {' '.join(recent_turns or [])}"
        )
        if not (_grounding_terms(question) & resume_terms):
            reasons.append("resume_project_ungrounded")
    for term in UNGROUNDED_TECH_TERMS:
        if term in lowered and term not in corpus:
            reasons.append("ungrounded_term")
            break

    if _looks_like_non_job_trivia(question, corpus=corpus):
        reasons.append("non_job_trivia")

    ok = not any(reason in BLOCKING_REASONS for reason in reasons)
    normalized = GeneratedQuestion(
        question=question,
        competency_id=expected_competency or generated.competency_id,
        intent=policy_intent or generated.intent,
        depth=max(
            1,
            min(
                5,
                int(max_depth),
                int(policy_depth or generated.depth or 1) + 1,
                int(generated.depth or policy_depth or 1),
            ),
        ),
        source_claim_ids=[item for item in generated.source_claim_ids if item in allowed_ids]
        if allowed_ids
        else list(generated.source_claim_ids),
        decision=generated.decision if generated.decision in {"probe", "advance"} else "probe",
        answer_evaluation=generated.answer_evaluation,
        depth_tag=generated.depth_tag,
        probe_shape=generated.probe_shape,
    )
    return ValidationResult(ok=ok, question=normalized, reasons=reasons)
