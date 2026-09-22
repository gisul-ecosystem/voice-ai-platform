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

_INTENT_ACTIONS = {
    "establish_context": PROBE_FOR_CONTEXT,
    "establish_ownership": PROBE_FOR_OWNERSHIP,
    "applied_understanding": PROBE_FOR_METHOD,
    "problem_or_complexity": PROBE_FOR_REASONING,
    "tradeoff_or_transfer": PROBE_FOR_REFLECTION,
}


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
    consecutive_no_gain_probes: int = 0
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
    clarify_after: int = 1
    rephrase_after: int = 2
    change_topic_after: int = 3
    close_after: int = 4


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
    close = max(change + 1, int(policy.get("close_after") or defaults["close_after"]))
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
    if state.consecutive_no_gain_probes >= 2:
        return PolicyDecision(
            action=(
                MOVE_TO_NEXT_COMPETENCY
                if state.has_uncovered_competencies
                else OFFER_FINAL_ADDITION
            ),
            forced_flow_decision="advance" if state.has_uncovered_competencies else "close",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="evidence_gap_stop",
            reason="two consecutive probes added no new evidence",
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
        return PolicyDecision(
            action=MAP_CANDIDATE_BACKGROUND,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=None,
            intent="candidate_map",
            reason="breadth-first mapping before deep probes",
            section="candidate_map",
        )

    if section == "candidate_map" and state.candidate_turn_count >= 1:
        return PolicyDecision(
            action=ASK_BASELINE,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=state.competency_id,
            intent="baseline",
            reason="candidate map complete — move into technical competency baseline",
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

    depth = max(1, min(state.probe_count + 1, state.max_depth))
    probes_exhausted = state.probe_count >= state.max_probes or depth >= state.max_depth
    if state.missing_intents and not probes_exhausted:
        next_intent = state.missing_intents[0]
        intent_depth = min(state.max_depth, max(depth, len(state.missing_intents)))
        action = _INTENT_ACTIONS.get(next_intent, _DEPTH_ACTIONS.get(depth, PROBE_FOR_CONTEXT))
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(intent_depth, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=next_intent,
            reason="required assessment intent still missing",
            section="competency_assessment",
        )

    if state.coverage_complete or probes_exhausted:
        if state.has_uncovered_competencies:
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=depth,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="coverage",
                reason="competency complete or probe budget exhausted",
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
        intent = state.missing_intents[0] if state.missing_intents else _DEPTH_ACTIONS.get(
            depth, PROBE_FOR_CONTEXT
        )
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

    return PolicyDecision(
        action=_DEPTH_ACTIONS.get(depth, PROBE_FOR_METHOD),
        forced_flow_decision="probe",
        allow_llm_decision=True,
        current_depth=depth,
        max_depth=state.max_depth,
        competency_id=state.competency_id,
        intent=_DEPTH_ACTIONS.get(depth, PROBE_FOR_METHOD),
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
