"""Deterministic next-action policy for structured interviews (Milestone 4).

The LLM phrases questions; this engine decides section, depth, probe/advance,
and closing. It cannot be overridden for hard limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


NextAction = str

OPEN_INTERVIEW = "OPEN_INTERVIEW"
MAP_CANDIDATE_BACKGROUND = "MAP_CANDIDATE_BACKGROUND"
ASK_BASELINE = "ASK_BASELINE"
CLARIFY_CURRENT_ANSWER = "CLARIFY_CURRENT_ANSWER"
PROBE_FOR_CONTEXT = "PROBE_FOR_CONTEXT"
PROBE_FOR_OWNERSHIP = "PROBE_FOR_OWNERSHIP"
PROBE_FOR_METHOD = "PROBE_FOR_METHOD"
PROBE_FOR_REASONING = "PROBE_FOR_REASONING"
PROBE_FOR_RESULT = "PROBE_FOR_RESULT"
PROBE_FOR_REFLECTION    = "PROBE_FOR_REFLECTION"
MOVE_TO_NEXT_COMPETENCY = "MOVE_TO_NEXT_COMPETENCY"
CHECK_REMAINING_GAP = "CHECK_REMAINING_GAP"
OFFER_FINAL_ADDITION = "OFFER_FINAL_ADDITION"
CLOSE_INTERVIEW = "CLOSE_INTERVIEW"

_DEPTH_ACTIONS = {
    1: PROBE_FOR_CONTEXT,
    2: PROBE_FOR_OWNERSHIP,
    3: PROBE_FOR_METHOD,
    4: PROBE_FOR_REASONING,
    5: PROBE_FOR_REFLECTION,
}

# Assessment intents (validator / coverage) — never put action names in PolicyDecision.intent.
_DEPTH_INTENTS = {
    1: "establish_context",
    2: "establish_ownership",
    3: "applied_understanding",
    4: "problem_or_complexity",
    5: "tradeoff_or_transfer",
}

_INTENT_ACTIONS = {
    "establish_context": PROBE_FOR_CONTEXT,
    "establish_ownership": PROBE_FOR_OWNERSHIP,
    "applied_understanding": PROBE_FOR_METHOD,
    "problem_or_complexity": PROBE_FOR_REASONING,
    "tradeoff_or_transfer": PROBE_FOR_REFLECTION,
}


def _assessment_intent(action: str, missing: list[str], *, depth: int) -> str:
    """Map policy action → ladder intent; prefer uncovered intents when present."""
    if missing:
        return missing[0]
    for intent, mapped in _INTENT_ACTIONS.items():
        if mapped == action:
            return intent
    return _DEPTH_INTENTS.get(depth, "establish_context")


@dataclass
class PolicyDecision:
    action: NextAction
    forced_flow_decision: str  # probe | advance | close
    allow_llm_decision: bool
    current_depth: int
    max_depth: int
    competency_id: str | None
    intent: str
    reason: str
    section: str


@dataclass
class PolicyState:
    candidate_turn_count: int = 0
    interviewer_turn_count: int = 0
    phase_index: int = 0
    probe_count: int = 0
    elapsed_seconds: int = 0
    consecutive_unusable: int = 0
    consecutive_explicit_unknown: int = 0
    completed: bool = False
    phase_name: str = ""
    competency_id: str | None = None
    max_depth: int = 4
    max_probes: int = 3
    soft_end_seconds: int = 27 * 60
    target_end_seconds: int = 30 * 60
    hard_end_seconds: int = 35 * 60
    min_elapsed_before_close_seconds: int = 0
    min_candidate_turns_before_close: int = 8
    at_last_competency: bool = False
    has_uncovered_competencies: bool = False
    missing_intents: list[str] = field(default_factory=list)
    coverage_complete: bool = False
    has_coverage_gaps: bool = False
    gap_competency_id: str | None = None
    consecutive_dry_probes: int = 0
    dry_probe_limit: int = 2
    clarify_after: int = 1
    rephrase_after: int = 2
    change_topic_after: int = 3
    close_after: int = 4
    # One reframed attempt allowed per competency+intent before abandoning.
    intent_repair_available: bool = False
    last_answer_usability: str = "usable"
    last_answer_quality: str = "adequate"
    usable_exchanges_on_competency: int = 0


def _answer_is_thin(state: PolicyState) -> bool:
    if state.last_answer_usability in {
        "too_short",
        "silence",
        "explicit_unknown",
        "off_topic",
    }:
        return True
    return state.last_answer_quality in {"unclear", "partial", "off_topic", "unsupported"}


def _answer_is_substantive(state: PolicyState) -> bool:
    return (
        state.last_answer_usability == "usable"
        and state.last_answer_quality in {"adequate", "strong", "partial", "sufficient"}
        and state.last_answer_quality not in {"off_topic", "unsupported"}
    )


def _may_close_or_wrap(state: PolicyState) -> bool:
    """Block early wrap-up before min time/turns (hard end still wins upstream)."""
    min_elapsed = max(
        0,
        int(state.min_elapsed_before_close_seconds)
        or int(state.target_end_seconds * 0.4),
    )
    if state.elapsed_seconds >= min_elapsed:
        return True
    return state.candidate_turn_count >= max(1, state.min_candidate_turns_before_close)


def outline_from_definition(definition: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a breadth-first outline from a published interview definition."""
    if not isinstance(definition, dict):
        return None
    competencies = definition.get("competencies")
    if not isinstance(competencies, list) or not competencies:
        return None
    time_policy = definition.get("time_policy") if isinstance(definition.get("time_policy"), dict) else {}
    duration = int(time_policy.get("duration_minutes") or 30)
    duration = 15 if duration < 20 else 45 if duration > 40 else 30

    phases: list[dict[str, Any]] = [
        {
            "name": "opening",
            "duration_minutes": 2,
            "topics": ["introduction", "role confirmation"],
            "source": "generic",
        },
        {
            "name": "candidate_map",
            "duration_minutes": 3,
            "topics": ["background", "relevant experience", "ownership"],
            "source": "generic",
        },
    ]
    usable_competencies: list[dict[str, Any]] = []
    for item in competencies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "").strip()
        if not _is_interviewable_phase_name(name):
            continue
        usable_competencies.append(item)
    if not usable_competencies:
        # Keep interview runnable even on a polluted published definition.
        usable_competencies = [
            item for item in competencies if isinstance(item, dict)
        ][:4]
    # Keep interviews deep: fewer competencies on short slots.
    max_comps = 3 if duration <= 20 else 4
    usable_competencies = usable_competencies[:max_comps]
    remaining = max(8, duration - 7)
    per = max(3, remaining // max(len(usable_competencies), 1))
    for item in usable_competencies:
        name = str(item.get("name") or item.get("id") or "competency").strip()
        evidence = [
            str(x).strip()
            for x in (item.get("evidence_expected") or [])
            if str(x).strip()
        ]
        phases.append(
            {
                "name": name,
                "duration_minutes": per,
                "topics": evidence[:4] or [name],
                "source": "jd",
                "competency_id": item.get("id"),
                "max_depth": int(item.get("max_depth") or 4),
                "max_probes": int(item.get("max_probes") or 3),
            }
        )
    phases.append(
        {
            "name": "closing",
            "duration_minutes": 2,
            "topics": ["final addition", "next steps"],
            "source": "generic",
        }
    )
    return {"phases": phases, "policy_mode": True}


_BARE_DUTY_PHASE_TOKENS = frozenset(
    {
        "design",
        "develop",
        "test",
        "build",
        "maintain",
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


def _is_interviewable_phase_name(name: str) -> bool:
    """Skip JD duty fragments that leaked into published competency names."""
    cleaned = (name or "").strip()
    if len(cleaned) < 3:
        return False
    words = cleaned.split()
    first = words[0].lower().strip(".,;:")
    if first in {"and", "or", "the", "a", "an", "to", "of", "for", "with"}:
        return False
    if len(words) == 1 and first in _BARE_DUTY_PHASE_TOKENS:
        return False
    if cleaned.lower().startswith("and "):
        return False
    if len(cleaned) > 72 and ("," in cleaned or cleaned.count(" ") >= 8):
        return False
    return True


def non_answer_bounds_from_definition(definition: dict[str, Any] | None) -> dict[str, int]:
    defaults = {
        "clarify_after": 1,
        "rephrase_after": 2,
        "change_topic_after": 3,
        "close_after": 4,
    }
    if not isinstance(definition, dict):
        return defaults
    policy = (
        definition.get("non_answer_policy")
        if isinstance(definition.get("non_answer_policy"), dict)
        else {}
    )
    clarify = max(1, int(policy.get("clarify_after") or defaults["clarify_after"]))
    rephrase = max(clarify, int(policy.get("rephrase_after") or defaults["rephrase_after"]))
    change = max(rephrase, int(policy.get("change_topic_after") or defaults["change_topic_after"]))
    # Published brain schema uses confirm_continue_after; agents historically used close_after.
    close_raw = policy.get("close_after")
    if close_raw is None:
        close_raw = policy.get("confirm_continue_after")
    close = max(change + 1, int(close_raw or defaults["close_after"]))
    return {
        "clarify_after": clarify,
        "rephrase_after": rephrase,
        "change_topic_after": change,
        "close_after": close,
    }


def time_bounds_from_definition(definition: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(definition, dict):
        return {
            "duration_minutes": 30,
            "soft_end_seconds": 27 * 60,
            "target_end_seconds": 30 * 60,
            "hard_end_seconds": 35 * 60,
        }
    policy = definition.get("time_policy") if isinstance(definition.get("time_policy"), dict) else {}
    duration = int(policy.get("duration_minutes") or 30)
    soft = int(policy.get("soft_end_minutes") or max(duration - 3, 1))
    target = int(policy.get("target_end_minutes") or duration)
    hard = int(policy.get("hard_end_minutes") or duration + 5)
    return {
        "duration_minutes": duration,
        "soft_end_seconds": soft * 60,
        "target_end_seconds": target * 60,
        "hard_end_seconds": hard * 60,
    }


def _section_for_phase(name: str) -> str:
    lowered = (name or "").lower()
    if any(token in lowered for token in ("open", "intro", "warm")):
        return "opening"
    if any(token in lowered for token in ("map", "background", "candidate")):
        return "candidate_map"
    if "clos" in lowered:
        return "closing"
    return "competency_assessment"


def decide_next_action(state: PolicyState) -> PolicyDecision:
    """Return the authoritative next action for the live turn."""
    if state.completed:
        return PolicyDecision(
            action=CLOSE_INTERVIEW,
            forced_flow_decision="close",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="closing",
            reason="interview already completed",
            section="completed",
        )

    if state.elapsed_seconds >= state.hard_end_seconds:
        return PolicyDecision(
            action=CLOSE_INTERVIEW,
            forced_flow_decision="close",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="closing",
            reason="hard time limit reached",
            section="closing",
        )

    # "I don't know": one same-topic clarify, then advance — not an instant hop.
    if state.last_answer_usability == "explicit_unknown":
        if state.consecutive_explicit_unknown < 2:
            return PolicyDecision(
                action=CLARIFY_CURRENT_ANSWER,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="clarify",
                reason="explicit unknown — one same-topic rephrase before moving on",
                section=_section_for_phase(state.phase_name),
            )
        if state.has_uncovered_competencies:
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="recovery",
                reason="second explicit unknown — advance topic",
                section=_section_for_phase(state.phase_name),
            )
        if _may_close_or_wrap(state):
            return PolicyDecision(
                action=OFFER_FINAL_ADDITION,
                forced_flow_decision="close",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="recovery",
                reason="second explicit unknown — wrap up",
                section="closing",
            )
        return PolicyDecision(
            action=PROBE_FOR_REFLECTION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="tradeoff_or_transfer",
            reason="too early to close — one reflective probe on last topic",
            section="competency_assessment",
        )

    if (
        state.consecutive_unusable >= state.clarify_after
        and state.consecutive_unusable < state.change_topic_after
    ):
        intent = (
            "rephrase"
            if state.consecutive_unusable >= state.rephrase_after
            else "clarify"
        )
        return PolicyDecision(
            action=CLARIFY_CURRENT_ANSWER,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=intent,
            reason="unusable answer requires clarification",
            section=_section_for_phase(state.phase_name),
        )

    if state.consecutive_unusable >= state.close_after:
        if not _may_close_or_wrap(state):
            if state.has_uncovered_competencies:
                return PolicyDecision(
                    action=MOVE_TO_NEXT_COMPETENCY,
                    forced_flow_decision="advance",
                    allow_llm_decision=False,
                    current_depth=1,
                    max_depth=state.max_depth,
                    competency_id=state.competency_id,
                    intent="recovery",
                    reason="repeated unusable — advance, too early to close",
                    section=_section_for_phase(state.phase_name),
                )
            return PolicyDecision(
                action=PROBE_FOR_REFLECTION,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="tradeoff_or_transfer",
                reason="repeated unusable — too early to close, one more probe",
                section="competency_assessment",
            )
        return PolicyDecision(
            action=CLOSE_INTERVIEW,
            forced_flow_decision="close",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="closing",
            reason="repeated unusable answers — controlled close",
            section="closing",
        )

    if state.consecutive_unusable >= state.change_topic_after:
        if state.has_uncovered_competencies:
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="recovery",
                reason="repeated unusable answers",
                section=_section_for_phase(state.phase_name),
            )
        if _may_close_or_wrap(state):
            return PolicyDecision(
                action=OFFER_FINAL_ADDITION,
                forced_flow_decision="close",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="recovery",
                reason="repeated unusable answers",
                section="closing",
            )
        return PolicyDecision(
            action=PROBE_FOR_REFLECTION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="tradeoff_or_transfer",
            reason="repeated unusable — too early to close",
            section="competency_assessment",
        )

    section = _section_for_phase(state.phase_name)

    if state.interviewer_turn_count == 0:
        return PolicyDecision(
            action=OPEN_INTERVIEW,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=1,
            competency_id=None,
            intent="opening",
            reason="interview has not opened",
            section="opening",
        )

    if state.candidate_turn_count == 0:
        return PolicyDecision(
            action=OPEN_INTERVIEW,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=1,
            competency_id=None,
            intent="await_introduction",
            reason="waiting for candidate introduction",
            section="opening",
        )

    if section == "opening" and state.candidate_turn_count <= 1:
        # Intro received — hop warmups so the spoken turn is already a competency ask.
        return PolicyDecision(
            action=MAP_CANDIDATE_BACKGROUND,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=None,
            intent="candidate_map",
            reason="intro received — advance toward competency baseline",
            section="candidate_map",
        )

    if section == "candidate_map" and state.candidate_turn_count <= 1:
        # Skip a second "tell me your background" turn after the opening intro.
        return PolicyDecision(
            action=ASK_BASELINE,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=state.competency_id or state.gap_competency_id,
            intent="establish_context",
            reason="intro complete — begin first competency question",
            section="baseline",
        )

    if section in {"opening", "candidate_map"}:
        return PolicyDecision(
            action=ASK_BASELINE,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=state.competency_id or state.gap_competency_id,
            intent="establish_context",
            reason="candidate map complete — move into technical competency baseline",
            section="baseline",
        )

    if section == "closing" or (
        state.elapsed_seconds >= state.soft_end_seconds and state.at_last_competency
    ):
        if state.elapsed_seconds >= state.target_end_seconds and _may_close_or_wrap(state):
            return PolicyDecision(
                action=CLOSE_INTERVIEW,
                forced_flow_decision="close",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="closing",
                reason="target end reached",
                section="closing",
            )
        if _may_close_or_wrap(state):
            return PolicyDecision(
                action=OFFER_FINAL_ADDITION,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=1,
                competency_id=state.competency_id,
                intent="final_addition",
                reason="soft end — offer final addition",
                section="closing",
            )
        return PolicyDecision(
            action=PROBE_FOR_RESULT
            if state.missing_intents
            else PROBE_FOR_REFLECTION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=(state.missing_intents[0] if state.missing_intents else "tradeoff_or_transfer"),
            reason="soft end reached early — deepen last competency before wrap",
            section="competency_assessment",
        )

    # Soft end while competencies remain: advance breadth-first — no new deep probes.
    if (
        state.elapsed_seconds >= state.soft_end_seconds
        and not state.at_last_competency
        and state.has_uncovered_competencies
    ):
        return PolicyDecision(
            action=MOVE_TO_NEXT_COMPETENCY,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=min(2, state.max_depth),
            competency_id=state.competency_id,
            intent="coverage",
            reason="soft end — advance remaining competencies without deeper probes",
            section="competency_assessment",
        )

    depth = max(1, min(state.probe_count + 1, state.max_depth))
    dry_exhausted = state.consecutive_dry_probes >= max(1, state.dry_probe_limit)
    probes_exhausted = (
        state.probe_count >= state.max_probes
        or depth >= state.max_depth
        or dry_exhausted
    )

    # Selective follow-up: intents covered + substantive answer → advance (no extra probe).
    if (
        not state.missing_intents
        and state.coverage_complete
        and _answer_is_substantive(state)
        and state.usable_exchanges_on_competency >= 1
    ):
        if state.has_uncovered_competencies:
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=depth,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="coverage",
                reason="intents covered with substantive answer — advance",
                section="competency_assessment",
            )
        if _may_close_or_wrap(state):
            return PolicyDecision(
                action=OFFER_FINAL_ADDITION,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=1,
                competency_id=state.competency_id,
                intent="final_addition",
                reason="all competencies covered — wrap up",
                section="closing",
            )
        return PolicyDecision(
            action=PROBE_FOR_REFLECTION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="tradeoff_or_transfer",
            reason="covered early — reflective probe until min interview length",
            section="competency_assessment",
        )

    if state.missing_intents and probes_exhausted and state.intent_repair_available:
        next_intent = state.missing_intents[0]
        action = _INTENT_ACTIONS.get(next_intent, PROBE_FOR_METHOD)
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(depth, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=next_intent,
            reason=(
                "one reframed repair before leaving intent — "
                "acknowledge what was said and narrow the gap"
            ),
            section="competency_assessment",
        )
    if state.missing_intents and not probes_exhausted:
        # Probe only while evidence is still missing (selective follow-up).
        next_intent = state.missing_intents[0]
        intent_depth = min(state.max_depth, max(depth, 1))
        action = _INTENT_ACTIONS.get(next_intent, _DEPTH_ACTIONS.get(depth, PROBE_FOR_CONTEXT))
        reason = "required assessment intent still missing"
        if _answer_is_thin(state):
            reason = "thin answer — concrete follow-up for missing intent"
        if state.consecutive_dry_probes:
            reason = (
                f"required assessment intent still missing "
                f"(dry probes {state.consecutive_dry_probes}/{state.dry_probe_limit})"
            )
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(intent_depth, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=next_intent,
            reason=reason,
            section="competency_assessment",
        )

    if state.coverage_complete or probes_exhausted:
        if state.has_uncovered_competencies:
            # Stay for a thin first answer while probe budget remains; once
            # probes are exhausted, advance even without a usable exchange.
            if (
                state.usable_exchanges_on_competency < 1
                and state.elapsed_seconds < state.soft_end_seconds
                and _answer_is_thin(state)
                and not probes_exhausted
            ):
                return PolicyDecision(
                    action=CLARIFY_CURRENT_ANSWER,
                    forced_flow_decision="probe",
                    allow_llm_decision=False,
                    current_depth=depth,
                    max_depth=state.max_depth,
                    competency_id=state.competency_id,
                    intent="clarify",
                    reason="no usable exchange yet — stay on competency",
                    section="competency_assessment",
                )
            reason = "competency complete or probe budget exhausted"
            if dry_exhausted and not state.coverage_complete:
                reason = "two follow-ups without new information — advance"
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=depth,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="coverage",
                reason=reason,
                section="competency_assessment",
            )
        if state.has_coverage_gaps or state.elapsed_seconds >= state.soft_end_seconds:
            return PolicyDecision(
                action=CHECK_REMAINING_GAP,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=2,
                competency_id=state.gap_competency_id or state.competency_id,
                intent="gap_check",
                reason="final coverage check before close",
                section="coverage_check",
            )
        if _may_close_or_wrap(state):
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=depth,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="coverage",
                reason="competency complete",
                section="competency_assessment",
            )
        return PolicyDecision(
            action=PROBE_FOR_REFLECTION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="tradeoff_or_transfer",
            reason="competency complete early — continue until min length",
            section="competency_assessment",
        )

    # Early competency turns: never allow multi-level jumps; LLM may only probe.
    if depth <= 2:
        action = ASK_BASELINE if depth == 1 else PROBE_FOR_OWNERSHIP
        intent = _assessment_intent(action, state.missing_intents, depth=depth)
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=intent,
            reason="progressive depth — establish context/ownership first",
            section="competency_assessment",
        )

    action = _DEPTH_ACTIONS.get(depth, PROBE_FOR_METHOD)
    return PolicyDecision(
        action=action,
        forced_flow_decision="probe",
        allow_llm_decision=True,
        current_depth=depth,
        max_depth=state.max_depth,
        competency_id=state.competency_id,
        intent=_assessment_intent(action, state.missing_intents, depth=depth),
        reason="controlled progressive depth",
        section="competency_assessment",
    )


def policy_prompt_block(decision: PolicyDecision) -> str:
    return (
        "POLICY ENGINE (authoritative — do not override):\n"
        f"- Required next action: {decision.action}\n"
        f"- Intent: {decision.intent}\n"
        f"- Section: {decision.section}\n"
        f"- Allowed depth now: {decision.current_depth} of {decision.max_depth}\n"
        f"- Flow decision must be: {decision.forced_flow_decision}\n"
        f"- Reason: {decision.reason}\n"
        "- Do not jump multiple depth levels.\n"
        "- Do not ask protected-class or prohibited questions.\n"
        "- Prefer applied work examples over trivia.\n"
        "- Do not ask acronym full-forms, puzzles, riddles, or brain-teasers unless job-critical.\n"
        "- Keep the same domain-neutral interviewer voice for any role.\n"
    )


def classify_answer_usability(text: str | None, *, min_words: int = 3) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "silence"
    lowered = cleaned.lower()
    if any(
        token in lowered
        for token in (
            "i don't know",
            "i do not know",
            "no idea",
            "not sure",
            "don't know more",
            "do not know more",
            "i'm doing this much",
            "i am doing this much",
        )
    ):
        return "explicit_unknown"
    words = cleaned.split()
    if len(words) < min_words:
        return "too_short"
    return "usable"
