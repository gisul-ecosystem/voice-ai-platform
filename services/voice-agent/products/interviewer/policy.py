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

# PolicyDecision.intent must always be a ladder intent, never an action name:
# downstream ladder/coverage lookups are keyed on these.
_DEPTH_INTENTS = {
    1: "establish_context",
    2: "establish_ownership",
    3: "applied_understanding",
    4: "problem_or_complexity",
    5: "tradeoff_or_transfer",
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
    valid = [item for item in competencies if isinstance(item, dict)]
    # Competencies are the assessment; the resume walkthrough only supplies
    # concrete material to probe. Reserve competency time FIRST, then spend what
    # is left on projects, so a long CV can never squeeze out a required skill.
    generic_minutes = 7
    min_per_competency = 3
    competency_floor = min_per_competency * max(len(valid), 1)
    project_pool = max(0, duration - generic_minutes - competency_floor)
    projects = [
        str(name).strip()
        for name in (resume_projects or [])
        if str(name).strip()
    ][: max(0, min(2, project_pool // 2))]
    project_budget = 2 if projects else 0
    for project in projects:
        phases.append(
            {
                "name": f"Resume project: {project}",
                "duration_minutes": project_budget,
                "topics": [project],
                "source": "resume",
                "project_name": project,
                "max_depth": 3,
                # One opener plus one follow-up: enough to surface the work,
                # not enough to eat the competency budget.
                "max_probes": 1,
            }
        )

    reserved = generic_minutes + project_budget * len(projects)
    remaining = max(competency_floor, duration - reserved)
    # Base pool of probes to distribute
    base_probes = 15
    weights = [max(0.0, float(item.get("weight") or 0)) for item in valid]
    weight_total = sum(weights)
    even = max(3, remaining // max(len(valid), 1))
    for item, weight in zip(valid, weights, strict=True):
        if weight_total > 0:
            share = max(3, round(remaining * weight / weight_total))
            normalized_weight = (weight / weight_total) * 100
        else:
            share = even
            normalized_weight = 100.0 / max(len(valid), 1)

        scaled_probes = max(2, round(base_probes * (normalized_weight / 100)))
        if normalized_weight < 20:
            scaled_depth = 3
        elif normalized_weight < 40:
            scaled_depth = 4
        else:
            scaled_depth = 5

        name = str(item.get("name") or item.get("id") or "competency").strip()
        evidence = [
            str(x).strip()
            for x in (item.get("evidence_expected") or [])
            if str(x).strip()
        ]
        
        cfg_depth = item.get("max_depth")
        cfg_probes = item.get("max_probes")

        phases.append(
            {
                "name": name,
                "duration_minutes": share,
                "topics": evidence[:4] or [name],
                "source": "jd",
                "competency_id": item.get("id"),
                "max_depth": int(cfg_depth) if cfg_depth else scaled_depth,
                "max_probes": int(cfg_probes) if cfg_probes else scaled_probes,
                "weight_normalized": normalized_weight,
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
            reason="candidate map complete — move into technical competency baseline",
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
        # Always chase the first (weakest / earliest) unmet assessment intent.
        next_intent = state.missing_intents[0]
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
            allow_llm_decision=True,
            current_depth=max(1, min(intent_depth, state.max_depth)),
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=next_intent,
            reason=reason,
            section="competency_assessment",
        )

    # Intents are covered but the evidence ledger still has an unproven slot:
    # keep probing that slot instead of counting the competency as done.
    if state.target_slot and not probes_exhausted:
        return PolicyDecision(
            action=SLOT_ACTIONS.get(state.target_slot, PROBE_FOR_METHOD),
            forced_flow_decision="probe",
            allow_llm_decision=True,
            current_depth=depth,
            max_depth=state.max_depth,
            competency_id=state.competency_id,
            intent=SLOT_INTENTS.get(state.target_slot, "applied_understanding"),
            reason=f"evidence slot '{state.target_slot}' not yet demonstrated",
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
    flow_instruction = (
        "- Flow decision: You may choose to 'probe' or 'advance'."
        if decision.allow_llm_decision
        else f"- Flow decision must be: {decision.forced_flow_decision}"
    )
    return (
        "POLICY ENGINE (authoritative — do not override):\n"
        f"- Required next action: {decision.action}\n"
        f"- Intent: {decision.intent}\n"
        f"- Section: {decision.section}\n"
        f"- Allowed depth now: {decision.current_depth} of {decision.max_depth}\n"
        f"{flow_instruction}\n"
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
