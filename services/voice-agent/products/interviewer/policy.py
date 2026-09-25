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
    evidence_topic: str = ""
    gap_kind: str = ""
    basis: str = ""
    probe_shape: str = ""
    delivery: str = ""
    move: str = ""


@dataclass
class FollowUpTarget:
    """Deterministic when / why / topic for one follow-up."""

    competency_id: str | None
    intent: str
    evidence_topic: str
    gap_kind: str
    basis: str
    probe_shape: str


@dataclass
class PolicyState:
    candidate_turn_count: int = 0
    interviewer_turn_count: int = 0
    phase_index: int = 0
    probe_count: int = 0
    elapsed_seconds: int = 0
    consecutive_unusable: int = 0
    completed: bool = False
    phase_name: str = ""
    competency_id: str | None = None
    max_depth: int = 4
    max_probes: int = 3
    soft_end_seconds: int = 27 * 60
    target_end_seconds: int = 30 * 60
    hard_end_seconds: int = 35 * 60
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
    answer_quality: str = ""
    asked_intent: str | None = None
    unmet_evidence: list[str] = field(default_factory=list)
    off_topic: bool = False
    hook_fact: str = ""
    factually_incorrect: bool = False
    last_probe_shape: str = ""
    previous_competency_id: str | None = None


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
    remaining = max(8, duration - 7)
    per = max(3, remaining // max(len(competencies), 1))
    for item in competencies:
        if not isinstance(item, dict):
            continue
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


_PROBE_SHAPE_ROTATION = ("why", "failure_mode", "metric", "trade_off")
_INTENT_PROBE_SHAPE = {
    "establish_context": "why",
    "establish_ownership": "why",
    "applied_understanding": "failure_mode",
    "problem_or_complexity": "metric",
    "tradeoff_or_transfer": "trade_off",
}
_TARGETED_ACTIONS = {
    ASK_BASELINE,
    CLARIFY_CURRENT_ANSWER,
    PROBE_FOR_CONTEXT,
    PROBE_FOR_OWNERSHIP,
    PROBE_FOR_METHOD,
    PROBE_FOR_REASONING,
    PROBE_FOR_RESULT,
    PROBE_FOR_REFLECTION,
    CHECK_REMAINING_GAP,
}


_INTENT_MOVE = {
    "establish_ownership": "their_part",
    "establish_context": "their_part",
    "applied_understanding": "the_decision",
    "problem_or_complexity": "what_changed",
    "tradeoff_or_transfer": "the_decision",
}


def interviewer_move(*, gap_kind: str, intent: str) -> str:
    """One pressure change. The subject stays the required evidence."""
    if (gap_kind or "").strip().lower() == "off_topic":
        return "cut_back"
    if (intent or "").strip() in {"final_addition", "closing"}:
        return "wrap"
    return _INTENT_MOVE.get((intent or "").strip(), "their_part")


def _shape_for_intent(intent: str, state: PolicyState) -> str:
    locked = _INTENT_PROBE_SHAPE.get(intent, "why")
    # Rotate only when the same intent was partially answered. Unclear or thin
    # re-asks stay on the intent's shape so a context probe does not become a metric.
    same_intent = (
        bool(state.asked_intent)
        and state.asked_intent == intent
        and state.probe_count > 0
        and state.answer_quality == "partial"
    )
    last = (state.last_probe_shape or "").strip()
    if same_intent and last in _PROBE_SHAPE_ROTATION:
        index = _PROBE_SHAPE_ROTATION.index(last)
        return _PROBE_SHAPE_ROTATION[(index + 1) % len(_PROBE_SHAPE_ROTATION)]
    return locked


def select_followup_target(state: PolicyState, *, intent: str) -> FollowUpTarget:
    """Name the single evidence topic and the gap that justify this probe."""
    from products.interviewer.coverage import classify_gap_kind, topic_for_intent

    topic = topic_for_intent(intent, state.unmet_evidence) or intent.replace("_", " ")
    thin = state.consecutive_dry_probes > 0
    gap = classify_gap_kind(
        answer_quality=state.answer_quality,
        off_topic=state.off_topic,
        contradictory=state.factually_incorrect,
        asked_intent=state.asked_intent,
        intent=intent,
        thin=thin,
    )
    hook = (state.hook_fact or "").strip()
    if gap == "partial" and hook:
        basis = f"They mentioned {hook}, but {topic} is still missing."
    elif gap == "off_topic":
        basis = f"The last answer left the competency. Bring the question back toward {topic}."
    elif gap == "contradictory":
        basis = f"The last answer contradicted an earlier claim about {topic}."
    elif gap == "unclear":
        basis = f"The last answer did not establish {topic}."
    elif gap == "thin":
        basis = f"The last follow-up added no new facts. Narrow to {topic}."
    elif hook:
        basis = f"Build on {hook}. Still missing {topic}."
    else:
        basis = f"Required evidence is still missing: {topic}."
    return FollowUpTarget(
        competency_id=state.competency_id,
        intent=intent,
        evidence_topic=topic,
        gap_kind=gap,
        basis=basis,
        probe_shape=_shape_for_intent(intent, state),
    )


def _attach_followup_target(decision: PolicyDecision, state: PolicyState) -> PolicyDecision:
    if decision.action not in _TARGETED_ACTIONS:
        if not decision.basis:
            decision.basis = decision.reason
        decision.delivery = _delivery_mode(decision, state)
        decision.move = interviewer_move(gap_kind=decision.gap_kind, intent=decision.intent)
        return decision
    intent = decision.intent
    if intent in {"clarify", "rephrase", "gap_check"}:
        intent = state.asked_intent or (
            state.missing_intents[0] if state.missing_intents else intent
        )
    target = select_followup_target(state, intent=intent)
    decision.evidence_topic = decision.evidence_topic or target.evidence_topic
    decision.gap_kind = decision.gap_kind or target.gap_kind
    decision.basis = decision.basis or target.basis
    decision.probe_shape = decision.probe_shape or target.probe_shape
    if decision.evidence_topic and decision.evidence_topic not in decision.reason:
        decision.reason = f"{decision.reason} — topic: {decision.evidence_topic}"
    decision.delivery = _delivery_mode(decision, state)
    decision.move = interviewer_move(
        gap_kind=decision.gap_kind, intent=intent or decision.intent
    )
    return decision


def _delivery_mode(decision: PolicyDecision, state: PolicyState) -> str:
    """How a hiring interviewer asks. Not the words they say."""
    if decision.section in {"opening", "candidate_map", "closing"} or decision.intent in {
        "opening",
        "await_introduction",
        "candidate_map",
        "closing",
        "final_addition",
    }:
        return "open"
    previous = state.previous_competency_id
    current = decision.competency_id
    if previous and current and previous != current:
        return "bridge"
    if decision.gap_kind in {"thin", "unclear", "off_topic", "partial", "contradictory"}:
        return "press"
    return "deepen"


def _probe_intent(state: PolicyState, fallback: str) -> str:
    """Stay on a partial or contradicted intent; otherwise take the first gap."""
    if (
        state.factually_incorrect
        and state.asked_intent
    ):
        return state.asked_intent
    if (
        state.answer_quality == "partial"
        and state.asked_intent
        and state.asked_intent in state.missing_intents
        and state.consecutive_dry_probes < max(1, state.dry_probe_limit)
    ):
        return state.asked_intent
    return fallback


def decide_next_action(state: PolicyState) -> PolicyDecision:
    """Return the authoritative next action for the live turn."""
    return _attach_followup_target(_decide_next_action(state), state)


def _decide_next_action(state: PolicyState) -> PolicyDecision:
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

    needs_clarify = (
        state.off_topic or state.consecutive_unusable >= state.clarify_after
    ) and state.consecutive_unusable < state.change_topic_after
    if needs_clarify:
        intent = (
            "rephrase"
            if state.consecutive_unusable >= state.rephrase_after
            else "clarify"
        )
        reason = (
            "off-topic answer — return to the open evidence topic"
            if state.off_topic
            else "unusable answer requires clarification"
        )
        return PolicyDecision(
            action=CLARIFY_CURRENT_ANSWER,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=intent,
            reason=reason,
            section=_section_for_phase(state.phase_name),
        )

    if state.consecutive_unusable >= state.close_after:
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
        return PolicyDecision(
            action=MOVE_TO_NEXT_COMPETENCY
            if state.has_uncovered_competencies
            else OFFER_FINAL_ADDITION,
            forced_flow_decision="advance"
            if state.has_uncovered_competencies
            else "close",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="recovery",
            reason="repeated unusable answers",
            section=_section_for_phase(state.phase_name),
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
        # Intro received while still on opening — advance into candidate_map so the
        # spoken map question lands on the map phase (flow multi-hops warmups).
        return PolicyDecision(
            action=MAP_CANDIDATE_BACKGROUND,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=None,
            intent="candidate_map",
            reason="breadth-first mapping before deep probes",
            section="candidate_map",
        )

    if section == "candidate_map" and state.candidate_turn_count <= 1:
        return PolicyDecision(
            action=MAP_CANDIDATE_BACKGROUND,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=None,
            intent="candidate_map",
            reason="ask for relevant background before competency probes",
            section="candidate_map",
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
            reason="candidate map complete — move into the first competency",
            section="baseline",
        )

    if section == "closing" or (
        state.elapsed_seconds >= state.soft_end_seconds and state.at_last_competency
    ):
        if state.elapsed_seconds >= state.target_end_seconds:
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
        timed_out = state.elapsed_seconds >= state.soft_end_seconds
        return PolicyDecision(
            action=OFFER_FINAL_ADDITION,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=1,
            competency_id=state.competency_id,
            intent="final_addition",
            reason=(
                "soft end — offer final addition"
                if timed_out
                else "required competencies are covered — invite one final addition and do not mention the clock"
            ),
            section="closing",
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
    if (
        state.factually_incorrect
        and state.asked_intent
        and not probes_exhausted
    ):
        next_intent = state.asked_intent
        action = _INTENT_ACTIONS.get(next_intent, PROBE_FOR_METHOD)
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(depth, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=next_intent,
            reason="contradicted claim — probe the same topic before advancing",
            section="competency_assessment",
        )
    if state.missing_intents and probes_exhausted and state.intent_repair_available:
        next_intent = _probe_intent(state, state.missing_intents[0])
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
        # Chase the first unmet intent, unless the answer just given was only partial.
        next_intent = _probe_intent(state, state.missing_intents[0])
        intent_depth = min(state.max_depth, max(depth, 1))
        action = _INTENT_ACTIONS.get(next_intent, _DEPTH_ACTIONS.get(depth, PROBE_FOR_CONTEXT))
        reason = "required assessment intent still missing"
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
        for token in ("i don't know", "i do not know", "no idea", "not sure")
    ):
        return "explicit_unknown"
    words = cleaned.split()
    if len(words) < min_words:
        return "too_short"
    return "usable"
