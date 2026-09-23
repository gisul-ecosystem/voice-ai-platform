"""Validate generated interview questions before they are spoken."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from products.interviewer.coverage import competency_by_id, ladder_steps
from products.interviewer.evidence import SLOT_KEYS

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

LEADING_PATTERNS = (
    re.compile(r"\b(?:right|correct|no)\s*\?\s*$"),
    re.compile(r",\s*(?:didn't|don't|doesn't|wasn't|weren't|isn't|aren't)\s+\w+\s*\?"),
    re.compile(r"^\s*so\s+you\s+(?:used|chose|built|went|picked|decided)\b"),
    re.compile(r"\bi\s+(?:assume|presume|take it)\b"),
)

# Only these justify discarding the model's question. Everything else is a
# quality note: worth a repair retry and worth logging, but a slightly imperfect
# real question beats a canned one that ignores what the candidate just said.
HARD_BLOCK_REASONS: frozenset[str] = frozenset(
    (
        "empty_question",
        "protected_topic",
    )
)


def is_speakable(reasons: list[str]) -> bool:
    """True when the question may be spoken despite failing validation."""
    return not any(reason in HARD_BLOCK_REASONS for reason in reasons)


TECH_TERMS = (
    "api",
    "schema",
    "queue",
    "kafka",
    "kubernetes",
    "redis",
    "postgres",
    "microservice",
    "latency",
    "deadlock",
    "timeout",
    "websocket",
    "sharding",
    "throughput",
    "cache",
    "database",
    "algorithm",
    "deploy",
    "server",
    "code",
)

INTENT_PROBE_ALIASES: dict[str, tuple[str, ...]] = {
    "establish_context": ("context", "situation", "describe", "walk me through", "tell me about"),
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

# Ladder intents are always valid; allowed_probes are example phrasings for the LLM,
# not a hard blocklist against assessment intents like establish_context.
STANDARD_ASSESSMENT_INTENTS = frozenset(INTENT_PROBE_ALIASES) - frozenset(
    {
        "clarify",
        "candidate_map",
        "opening",
        "baseline",
        "final_addition",
        "gap_check",
        "closing",
        "recovery",
    }
)
KNOWN_INTENTS = frozenset(INTENT_PROBE_ALIASES) | STANDARD_ASSESSMENT_INTENTS | SKIP_HOOK_INTENTS

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
    # Evidence dimensions (evidence.SLOT_KEYS) this answer actually proved / merely asserted.
    slots_demonstrated: list[str] = field(default_factory=list)
    slots_claimed: list[str] = field(default_factory=list)
    contradicts_earlier: bool = False

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
        }


def _slot_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        if key in SLOT_KEYS and key not in seen:
            seen.append(key)
    return seen


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
    return AnswerEvaluation(
        technical_substance=substance,  # type: ignore[arg-type]
        key_facts_stated=facts[:20],
        reasoning=str(payload.get("reasoning") or "").strip()[:500],
        matches_evidence_expected=bool(payload.get("matches_evidence_expected")),
        needs_clarification=bool(payload.get("needs_clarification")),
        factually_correct=bool(payload.get("factually_correct", True)),
        slots_demonstrated=_slot_list(payload.get("slots_demonstrated")),
        slots_claimed=_slot_list(payload.get("slots_claimed")),
        contradicts_earlier=bool(payload.get("contradicts_earlier")),
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


def _near_duplicate(left: str, right: str, *, threshold: float = 0.7) -> bool:
    left_tokens = _question_tokens(left)
    right_tokens = _question_tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap / min(len(left_tokens), len(right_tokens)) >= threshold


def _same_question_frame(left: str, right: str, *, tokens: int = 4) -> bool:
    """True when the opening ask frame matches (e.g. 'can you describe the specific …')."""
    a = prefix_tokens(left, tokens)
    b = prefix_tokens(right, tokens)
    return len(a) >= tokens and a == b


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
        "problem_or_complexity": "What was difficult about that?",
        "tradeoff_or_transfer": "Looking back, what would you change?",
        "gap_check": "Can you share one concrete example from that work?",
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
        "Can you share one concrete example from that work?",
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
    for item in competency.get("evidence_expected") or []:
        parts.append(str(item))
    if isinstance(profile, dict):
        for item in profile.get("claims") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("value") or ""))
    return " ".join(parts).lower()


def _intent_allowed_by_probes(intent: str, allowed_probes: list[str]) -> bool:
    intent = canonical_intent(intent)
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
    # Published ladder intents are always permitted; allowed_probes guide phrasing.
    if intent in STANDARD_ASSESSMENT_INTENTS:
        return True
    if not allowed_probes:
        return True
    aliases = INTENT_PROBE_ALIASES.get(intent, ())
    blob = " ".join(allowed_probes).lower()
    if intent.replace("_", " ") in blob:
        return True
    return any(alias in blob for alias in aliases)


_LEADING_MARKERS = (
    "don't you think",
    "do you not think",
    "wouldn't you agree",
    "wouldnt you agree",
    "isn't it true",
    "isnt it true",
    "you must have",
    "you obviously",
    "surely you",
    "of course you",
    "wouldn't you say",
    "wouldnt you say",
    "right?",
    ", right?",
)

_COMPOUND_CONJUNCTIONS = frozenset({"and", "or"})
_COMPOUND_WH = frozenset(
    {"how", "what", "why", "when", "who", "which", "where"}
)
# Auxiliaries that open a second yes/no ask after a conjunction ("and did you…").
_COMPOUND_AUX = frozenset(
    {"did", "do", "does", "can", "could", "would", "should", "have", "has", "is", "are"}
)
_COMPOUND_IF = frozenset({"if", "whether"})
# Ask verbs that make "…and if you…" a disguised second question (sparse fixture).
_COMPOUND_ASK_VERBS = frozenset(
    {
        "share",
        "tell",
        "describe",
        "determine",
        "explain",
        "discuss",
        "outline",
        "clarify",
        "walk",
    }
)
# Look ahead this many tokens after and/or for an interrogative opener.
_COMPOUND_LOOKAHEAD = 4


def looks_like_compound_question(question: str) -> bool:
    """True when the spoken text packs two asks into one turn.

    Fires on:
    - more than one '?'
    - coordinating ``and``/``or`` followed within a few tokens by a wh-word
      or interrogative auxiliary (``and how`` / ``and did``)
    - ``and``/``or`` + ``if``/``whether`` when an ask verb (share/tell/describe/…)
      already appeared earlier — catches the sparse single-'?' pattern
      ("share how you determined X, and if you encountered Y")
    """
    text = (question or "").strip()
    if not text:
        return False
    if text.count("?") > 1:
        return True
    tokens = fingerprint(text).split()
    if len(tokens) < 4:
        return False
    for index, token in enumerate(tokens):
        if token not in _COMPOUND_CONJUNCTIONS:
            continue
        window = tokens[index + 1 : index + 1 + _COMPOUND_LOOKAHEAD]
        if not window:
            continue
        if any(item in _COMPOUND_WH or item in _COMPOUND_AUX for item in window):
            return True
        if any(item in _COMPOUND_IF for item in window):
            earlier = tokens[:index]
            if any(verb in earlier for verb in _COMPOUND_ASK_VERBS):
                return True
    return False


def _looks_like_leading_question(lowered: str) -> bool:
    """Block questions that put the preferred answer into the candidate's mouth."""
    if not lowered:
        return False
    if any(marker in lowered for marker in _LEADING_MARKERS):
        return True
    # "So you mainly just X?" / "So you were only responsible for Y?"
    if lowered.startswith("so you ") and any(
        token in lowered for token in (" just ", " only ", " mainly ", " simply ")
    ):
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
    if _looks_like_leading_question(lowered):
        reasons.append("leading_question")
    if any(marker in lowered for marker in PROTECTED_MARKERS):
        reasons.append("protected_topic")
    live_probe = (policy_intent or "") not in SKIP_HOOK_INTENTS
    if live_probe:
        hook = (hook_fact or "").strip()
        if hook and not is_clean_hook_fact(hook):
            reasons.append("invalid_hook_phrase")
        else:
            stems = hook_stem_tokens(hook)
            if stems and not any(stem in lowered for stem in stems):
                reasons.append("missing_hook_stem")
        current_prefix = prefix_tokens(question)
        if len(current_prefix) >= 6:
            for previous in recent_questions[-8:]:
                previous_prefix = prefix_tokens(previous)
                if len(previous_prefix) >= 6 and current_prefix == previous_prefix:
                    reasons.append("repeated_prefix")
                    break
        if (
            required_probe_shape
            and generated.probe_shape
            and last_probe_shape
            and generated.probe_shape == last_probe_shape
        ):
            reasons.append("repeated_probe_shape")

    expected_competency = policy_competency_id
    if expected_competency and generated.competency_id not in {None, "", expected_competency}:
        reasons.append("competency_mismatch")
    # JSON intent is metadata only. Normalized output overwrites it to policy_intent.
    # Failing the turn for a label mismatch discarded hooked follow-ups.
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
    # Only guard jargon for roles with no technical signal at all. Banning these
    # words outright would stop a technical interview from ever going deep.
    if corpus and not any(term in corpus for term in TECH_TERMS):
        if any(term in lowered for term in TECH_TERMS):
            reasons.append("ungrounded_term")

    if _looks_like_non_job_trivia(question, corpus=corpus):
        reasons.append("non_job_trivia")

    # We still collect all reasons for logging and analysis, but we only block
    # the question (force fallback) if it is genuinely empty. We want the real LLM
    # generated question to reach TTS, despite minor stylistic issues.
    ok = "empty_question" not in reasons
    normalized = GeneratedQuestion(
        question=question,
        competency_id=expected_competency or generated.competency_id,
        intent=policy_intent or generated.intent,
        depth=max(1, min(5, int(policy_depth or generated.depth or 1))),
        source_claim_ids=[item for item in generated.source_claim_ids if item in allowed_ids]
        if allowed_ids
        else list(generated.source_claim_ids),
        decision=generated.decision if generated.decision in {"probe", "advance"} else "probe",
        answer_evaluation=generated.answer_evaluation,
        depth_tag=generated.depth_tag,
        probe_shape=generated.probe_shape,
    )
    return ValidationResult(ok=ok, question=normalized, reasons=reasons)
