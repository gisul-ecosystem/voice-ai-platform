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
WALK_RESUME_PROJECT = "WALK_RESUME_PROJECT"
CLARIFY_CURRENT_ANSWER = "CLARIFY_CURRENT_ANSWER"
PROBE_FOR_CONTEXT = "PROBE_FOR_CONTEXT"
PROBE_FOR_OWNERSHIP = "PROBE_FOR_OWNERSHIP"
PROBE_FOR_METHOD = "PROBE_FOR_METHOD"
PROBE_FOR_REASONING = "PROBE_FOR_REASONING"
PROBE_FOR_RESULT = "PROBE_FOR_RESULT"
PROBE_FOR_REFLECTION    = "PROBE_FOR_REFLECTION"
PROBE_FOR_CONSISTENCY = "PROBE_FOR_CONSISTENCY"
MOVE_TO_NEXT_COMPETENCY = "MOVE_TO_NEXT_COMPETENCY"
CHECK_REMAINING_GAP = "CHECK_REMAINING_GAP"
OFFER_FINAL_ADDITION = "OFFER_FINAL_ADDITION"
CLOSE_INTERVIEW = "CLOSE_INTERVIEW"

# Intro + optional project must yield to admin competencies quickly.
WARMUP_MAX_SECONDS = 180
WARMUP_MAX_INTERVIEWER_TURNS = 5
WARMUP_SECTIONS = frozenset({"opening", "candidate_map", "resume_project", "baseline"})

# Probe rungs (design spec section 5). The policy picks the rung; the model
# only supplies the wording.
PROBE_RUNGS: dict[str, str] = {
    "ownership": PROBE_FOR_OWNERSHIP,
    "specifying": PROBE_FOR_METHOD,
    "mechanism": PROBE_FOR_METHOD,
    "metric": PROBE_FOR_RESULT,
    "tradeoff": PROBE_FOR_REASONING,
    "failure_mode": PROBE_FOR_REASONING,
    "optimization": PROBE_FOR_REFLECTION,
}

# Which ladder intent each evidence slot is pursued under.
SLOT_INTENTS: dict[str, str] = {
    "ownership": "establish_ownership",
    "approach": "applied_understanding",
    "mechanism": "applied_understanding",
    "complexity_or_cost": "problem_or_complexity",
    "tradeoff": "tradeoff_or_transfer",
    "failure_mode": "problem_or_complexity",
    "optimization": "tradeoff_or_transfer",
    "measurement": "problem_or_complexity",
}

SLOT_ACTIONS: dict[str, str] = {
    "ownership": PROBE_FOR_OWNERSHIP,
    "approach": PROBE_FOR_METHOD,
    "mechanism": PROBE_FOR_METHOD,
    "complexity_or_cost": PROBE_FOR_REASONING,
    "tradeoff": PROBE_FOR_REASONING,
    "failure_mode": PROBE_FOR_REASONING,
    "optimization": PROBE_FOR_REFLECTION,
    "measurement": PROBE_FOR_RESULT,
}

_DEPTH_ACTIONS = {
    1: PROBE_FOR_CONTEXT,
    2: PROBE_FOR_METHOD,
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

# PolicyDecision.intent must always be a ladder intent, never an action name:
# downstream ladder/coverage lookups are keyed on these.
_DEPTH_INTENTS = {
    1: "establish_context",
    2: "establish_ownership",
    3: "applied_understanding",
    4: "problem_or_complexity",
    5: "tradeoff_or_transfer",
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
    # Consecutive probes on this competency that moved no evidence forward.
    probes_without_gain: int = 0
    no_gain_stop_after: int = 4
    # Weakest unproven evidence slot for the active competency, if any.
    target_slot: str | None = None
    # Set when the last answer contradicted something said earlier.
    contradiction_pending: bool = False
    # Resume project being walked through, when the active phase is a project phase.
    project_name: str | None = None
    # Set once the closing "anything to add?" has already been asked.
    final_addition_offered: bool = False
    clarify_after: int = 1
    rephrase_after: int = 2
    change_topic_after: int = 5
    close_after: int = 7


def outline_from_definition(
    definition: dict[str, Any] | None,
    *,
    resume_projects: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build a breadth-first outline from a published interview definition."""
    if not isinstance(definition, dict):
        return None
    competencies = definition.get("competencies")
    if not isinstance(competencies, list) or not competencies:
        return None
    time_policy = definition.get("time_policy") if isinstance(definition.get("time_policy"), dict) else {}
    duration = int(time_policy.get("duration_minutes") or 30)
    # Accept 15, 20, 30, or 45. Snap to nearest allowed value.
    # 20-minute interviews are fully supported for focused 3-4 competency sessions.
    ALLOWED = (15, 20, 30, 45)
    duration = min(ALLOWED, key=lambda d: abs(d - duration))

    phases: list[dict[str, Any]] = [
        {
            "name": "opening",
            "duration_minutes": 1,
            "topics": ["introduction", "role confirmation"],
            "source": "generic",
        },
    ]
    valid = [item for item in competencies if isinstance(item, dict)]
    # Keep intro+projects short so admin competencies start within ~3 minutes.
    # Opening 1 + closing 1; at most one brief project question before JD skills.
    generic_minutes = 2
    # Guarantee every competency gets at least 4 minutes (1 baseline + 3 probes).
    # With 6 competencies this gives floor of 24 min — leaves 6 min for opening/project/closing.
    min_per_competency = 4
    competency_floor = min_per_competency * max(len(valid), 1)
    # Project warm-up: only allow if budget permits without cutting competency floor.
    # Hard cap: 3 minutes total for project regardless of total duration.
    max_project_minutes = 3
    project_pool = min(max_project_minutes, max(0, duration - generic_minutes - competency_floor))
    projects = [
        str(name).strip()
        for name in (resume_projects or [])
        if str(name).strip()
    ][: 1 if project_pool >= 1 else 0]
    for project in projects:
        phases.append(
            {
                "name": f"Resume project: {project}",
                "duration_minutes": max(1, project_pool),
                "topics": [project],
                "source": "resume",
                "intent": "resume_project",
                "project_name": project,
                "max_depth": 3,
                "max_probes": 4,  # 1 opening + 4 probes = 5 total project turns
            }
        )

    reserved = generic_minutes + sum(
        int(phase.get("duration_minutes") or 0)
        for phase in phases
        if phase.get("intent") == "resume_project"
    )
    remaining = max(competency_floor, duration - reserved)
    # Distribute remaining time by recruiter weight.
    # Uses round() so equal-weight competencies always get the same value.
    # Rounding may produce sum != remaining by at most ±n; we correct by trimming
    # or adding to the competency with the largest/smallest share without breaking
    # equal-weight symmetry (equal items all round identically — only one needs trim).
    weights = [max(0.0, float(item.get("weight") or 0)) for item in valid]
    weight_total = sum(weights)
    n_valid = max(len(valid), 1)

    if weight_total > 0:
        raw_shares = [
            max(min_per_competency, round(remaining * w / weight_total))
            for w in weights
        ]
    else:
        # Pure equal split: integer division so all shares identical when n divides evenly.
        base = remaining // n_valid
        raw_shares = [max(min_per_competency, base)] * n_valid

    # Correct sum to exactly equal remaining by adjusting one item at a time,
    # always picking the item where the adjustment is least noticeable (largest
    # or smallest share). Equal-weight items all have the same value so this
    # only ever adjusts one of them, preserving practical symmetry.
    diff = remaining - sum(raw_shares)
    if diff > 0:
        for _ in range(diff):
            # Add to the item with the smallest current share (most underserved)
            raw_shares[min(range(n_valid), key=lambda i: raw_shares[i])] += 1
    elif diff < 0:
        for _ in range(-diff):
            # Remove from the item with the largest current share
            idx = max(range(n_valid), key=lambda i: raw_shares[i])
            raw_shares[idx] = max(min_per_competency, raw_shares[idx] - 1)

    for item, share in zip(valid, raw_shares, strict=True):
        name = str(item.get("name") or item.get("id") or "competency").strip()
        evidence = [
            str(x).strip()
            for x in (item.get("evidence_expected") or [])
            if str(x).strip()
        ]
        phases.append(
            {
                "name": name,
                "duration_minutes": share,
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
            "duration_minutes": 1,
            "topics": ["final addition", "next steps"],
            "source": "generic",
        }
    )
    return {"phases": phases, "policy_mode": True}


def non_answer_bounds_from_definition(definition: dict[str, Any] | None) -> dict[str, int]:
    defaults = {
        "clarify_after": 1,
        "rephrase_after": 2,
        "change_topic_after": 5,
        "close_after": 7,
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
    # Compute a competency-count-aware soft end so the breadth-first rush
    # only fires after all competencies have had at least one real question.
    # Minimum: 4 min per competency + 4 min for opening/project/closing.
    n_competencies = len([
        c for c in (definition.get("competencies") or [])
        if isinstance(c, dict)
    ])
    min_competency_coverage_minutes = max(n_competencies * 4, 0)
    earliest_soft = min(min_competency_coverage_minutes + 4, duration - 2)
    soft_from_policy = int(policy.get("soft_end_minutes") or max(duration - 3, 1))
    # Use whichever is later — never rush before all competencies are reachable.
    soft = max(soft_from_policy, earliest_soft)
    soft = min(soft, duration - 1)  # never exceed duration
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
    if lowered.startswith("resume project"):
        return "resume_project"
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

    # Hard cap: resume/project warm-up never exceeds 3 follow-up probes.
    # After 3 probes the engine forces advance to the first competency.
    # This is checked BEFORE any clarify/unusable logic so a run of unclear
    # answers during the project cannot extend it indefinitely.
    _in_project_phase = "resume project" in (state.phase_name or "").lower()
    if _in_project_phase and state.probe_count >= 3:
        return PolicyDecision(
            action=MOVE_TO_NEXT_COMPETENCY,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="coverage",
            reason="resume project 3-probe cap reached — advancing to competencies",
            section="competency_assessment",
        )

    if (
        state.consecutive_unusable >= state.clarify_after
        and state.consecutive_unusable < state.change_topic_after
    ):
        # Inside a resume-project phase, CLARIFY fires the same full prompt and
        # the LLM tends to produce the identical question (as seen in Q3/Q4).
        # Instead, route to WALK_RESUME_PROJECT with a 'different angle' reason
        # so the LLM knows to ask about mechanism/decision/challenge, not repeat.
        if _in_project_phase:
            return PolicyDecision(
                action=WALK_RESUME_PROJECT,
                forced_flow_decision="probe",
                allow_llm_decision=False,
                current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="establish_ownership",
                reason="unclear answer in project phase — ask a different project angle (mechanism/decision/challenge, not a repeat)",
                section="resume_project",
            )
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
    if state.consecutive_no_gain_probes >= 4:
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

    # A contradiction is the highest-value thing to resolve and can fire from any
    # rung, but never before the interview has actually started.
    if (
        state.contradiction_pending
        and state.competency_id
        and section == "competency_assessment"
    ):
        return PolicyDecision(
            action=PROBE_FOR_CONSISTENCY,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=max(1, min(state.probe_count + 1, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="consistency_check",
            reason="answer conflicts with an earlier statement",
            section="competency_assessment",
        )

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

    if section in WARMUP_SECTIONS and (
        state.elapsed_seconds >= WARMUP_MAX_SECONDS
        or state.interviewer_turn_count >= WARMUP_MAX_INTERVIEWER_TURNS
    ):
        return PolicyDecision(
            action=MOVE_TO_NEXT_COMPETENCY,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=state.competency_id,
            intent="coverage",
            reason="warmup budget done — start admin competencies",
            section=section,
        )

    if section == "opening" and state.candidate_turn_count >= 1:
        return PolicyDecision(
            action=ASK_BASELINE,
            forced_flow_decision="advance",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=2,
            competency_id=state.competency_id,
            intent="baseline",
            reason="introduction complete — start the resume walkthrough or competencies",
            section="opening",
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
            reason="candidate map complete — move into the resume walkthrough",
            section="baseline",
        )

    if section == "resume_project":
        depth = max(1, min(state.probe_count + 1, state.max_depth))
        if state.probe_count >= state.max_probes:
            return PolicyDecision(
                action=MOVE_TO_NEXT_COMPETENCY,
                forced_flow_decision="advance",
                allow_llm_decision=False,
                current_depth=depth,
                max_depth=state.max_depth,
                competency_id=None,
                intent="coverage",
                reason="resume project covered — move to the next section",
                section="resume_project",
            )
        return PolicyDecision(
            action=WALK_RESUME_PROJECT,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=None,
            intent="resume_project"
            if state.probe_count == 0
            else "applied_understanding",
            reason=f"walking the candidate's own project: {state.project_name or 'resume project'}",
            section="resume_project",
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
        if state.final_addition_offered:
            # Asking "anything else?" repeatedly is the closing-loop failure mode.
            return PolicyDecision(
                action=CLOSE_INTERVIEW,
                forced_flow_decision="close",
                allow_llm_decision=False,
                current_depth=1,
                max_depth=state.max_depth,
                competency_id=state.competency_id,
                intent="closing",
                reason="final addition already offered",
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

    # Soft end while competencies remain: advance breadth-first — no new deep probes.
    # Never advance if probe_count == 0 (must ask at least baseline).
    _min_probes_for_soft_advance = 1
    if (
        state.elapsed_seconds >= state.soft_end_seconds
        and not state.at_last_competency
        and state.has_uncovered_competencies
        and state.probe_count >= _min_probes_for_soft_advance
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
    probes_exhausted = state.probe_count >= state.max_probes or depth >= state.max_depth

    # Hard gate: if we haven't asked a single real question on this competency yet,
    # never advance — force a baseline question regardless of other policy signals.
    if state.probe_count == 0 and state.competency_id and section == "competency_assessment":
        return PolicyDecision(
            action=ASK_BASELINE,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=1,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="establish_context",
            reason="no question asked on this competency yet — must ask at least one",
            section="competency_assessment",
        )

    # Diminishing returns: stop drilling a seam that has stopped producing evidence.
    if (
        state.probes_without_gain >= state.no_gain_stop_after
        and state.competency_id
        and not probes_exhausted
    ):
        return PolicyDecision(
            action=MOVE_TO_NEXT_COMPETENCY
            if state.has_uncovered_competencies
            else OFFER_FINAL_ADDITION,
            forced_flow_decision="advance"
            if state.has_uncovered_competencies
            else "close",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent="coverage" if state.has_uncovered_competencies else "final_addition",
            reason="probes stopped yielding new evidence",
            section="competency_assessment",
        )

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

    # Intents are covered but the evidence ledger still has an unproven slot:
    # keep probing that slot instead of counting the competency as done.
    if state.target_slot and not probes_exhausted:
        return PolicyDecision(
            action=SLOT_ACTIONS.get(state.target_slot, PROBE_FOR_METHOD),
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=SLOT_INTENTS.get(state.target_slot, "applied_understanding"),
            reason=f"evidence slot '{state.target_slot}' not yet demonstrated",
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
        action = ASK_BASELINE if depth == 1 else PROBE_FOR_METHOD
        intent = state.missing_intents[0] if state.missing_intents else _DEPTH_INTENTS.get(
            depth, "establish_context"
        )
        return PolicyDecision(
            action=action,
            forced_flow_decision="probe",
            allow_llm_decision=False,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=intent,
            reason="progressive depth — baseline concept followed by applied method",
            section="competency_assessment",
        )

    return PolicyDecision(
        action=_DEPTH_ACTIONS.get(depth, PROBE_FOR_METHOD),
        forced_flow_decision="probe",
        allow_llm_decision=True,
        current_depth=depth,
        max_depth=state.max_depth,
        competency_id=state.competency_id,
        intent=_DEPTH_INTENTS.get(depth, "applied_understanding"),
        reason="controlled progressive depth",
        section="competency_assessment",
    )


def policy_prompt_block(decision: PolicyDecision) -> str:
    return (
        "AGENDA (section and timing only — invent the spoken question yourself):\n"
        f"- Section: {decision.section}\n"
        f"- Current competency id: {decision.competency_id or '(none)'}\n"
        f"- Stay or move: {decision.forced_flow_decision}\n"
        f"- Reason: {decision.reason}\n"
        "- Do not ask protected-class or prohibited questions.\n"
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
