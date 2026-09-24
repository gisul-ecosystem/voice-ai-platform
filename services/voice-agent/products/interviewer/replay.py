"""Follow-up replay harness and human rubric for recorded sessions."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from products.interviewer.coverage import apply_coverage
from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import (
    CHECK_REMAINING_GAP,
    CLARIFY_CURRENT_ANSWER,
    CLOSE_INTERVIEW,
    MOVE_TO_NEXT_COMPETENCY,
    OFFER_FINAL_ADDITION,
    PolicyDecision,
)
from products.interviewer.validator import (
    AnswerEvaluation,
    extract_hook_fact,
    hook_stem_tokens,
    next_probe_shape,
    prefix_tokens,
)

Scenario = Literal[
    "thin_answer",
    "ownership_dodge",
    "metric_named",
    "contradiction",
    "time_up",
]

RUBRIC_CRITERIA = (
    "logical",
    "hooked",
    "non_repeating",
    "thin_answers",
    "accurate",
)

_RECOVERY_ACTIONS = {
    CLARIFY_CURRENT_ANSWER,
    MOVE_TO_NEXT_COMPETENCY,
    OFFER_FINAL_ADDITION,
    CLOSE_INTERVIEW,
    CHECK_REMAINING_GAP,
}


class _UnusedLlm:
    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        raise RuntimeError("replay harness does not call the phrasing model")


def replay_definition() -> dict[str, Any]:
    return {
        "definition_id": "idef_replay_be_01",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
        },
        "non_answer_policy": {
            "clarify_after": 1,
            "rephrase_after": 2,
            "change_topic_after": 3,
        },
        "job_intelligence": {
            "role": {"title": "Backend Engineer", "target_level": "mid"},
            "raw_job_description": "Own Python services, incidents, and API reliability.",
        },
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
        ],
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "definition": "Identifies and resolves backend problems",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": [
                    "context of the work",
                    "personal contribution",
                    "approach or method",
                ],
            },
            {
                "id": "reliability",
                "name": "Reliability",
                "definition": "Keeps services available under failure",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": [
                    "incident context",
                    "personal contribution",
                    "measured outcome",
                ],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "problem_solving",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "example_question": "When did you work on that service, and for whom?",
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "example_question": "What part of that did you personally handle?",
                    },
                    {
                        "depth": 3,
                        "intent": "applied_understanding",
                        "example_question": "How did you decide on that approach?",
                    },
                ],
            },
            {
                "competency_id": "reliability",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "example_question": "What incident were you dealing with?",
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "example_question": "What did you personally do during that incident?",
                    },
                ],
            },
        ],
    }


@dataclass(frozen=True)
class RecordedSession:
    fixture_id: str
    scenario: Scenario
    last_answer: str
    asked_intent: str
    competency_id: str
    expected_intent: str
    expected_action: str
    expected_competency_id: str
    interviewer_turns: tuple[str, ...]
    prior_candidate_turns: tuple[str, ...]
    pre_covered: tuple[str, ...] = ()
    probe_count: int = 1
    phase_index: int = 2
    elapsed_seconds: int = 600
    consecutive_unusable: int = 0
    consecutive_explicit_unknown: int = 0
    last_probe_shape: str = "why"
    profile_type: str = "experienced"
    job_target_level: str = "mid"
    factually_correct: bool | None = None
    hook_stem: str | None = None
    allow_competency_change: bool = False
    must_not_cover: tuple[str, ...] = ()


@dataclass
class ReplayResult:
    fixture: RecordedSession
    decision: PolicyDecision
    missing_before: list[str]
    missing_after: list[str]
    covered_after: list[str]
    published_ids: list[str]
    fallback_question: str
    hook_fact: str
    next_shape: str


@dataclass
class RubricVerdict:
    fixture_id: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


_DEFAULT_QUESTIONS = (
    "Thanks for joining. Please introduce yourself.",
    "What work from your background is most relevant to this Backend Engineer role?",
    "When did you work on the billing retries, and for whom?",
)
_DEFAULT_ANSWERS = (
    "I am a backend engineer who interned on billing retries.",
    "I worked on the billing retries service in Python.",
)


def recorded_sessions() -> list[RecordedSession]:
    """Twenty recorded follow-up turns used as the CI / human-review corpus."""
    return [
        RecordedSession(
            fixture_id="thin_01_unknown",
            scenario="thin_answer",
            last_answer="I don't know.",
            asked_intent="establish_context",
            competency_id="problem_solving",
            expected_intent="clarify",
            expected_action=CLARIFY_CURRENT_ANSWER,
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            must_not_cover=("establish_context", "establish_ownership"),
        ),
        RecordedSession(
            fixture_id="thin_02_too_short",
            scenario="thin_answer",
            last_answer="Yeah.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="clarify",
            expected_action=CLARIFY_CURRENT_ANSWER,
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="thin_03_rephrase",
            scenario="thin_answer",
            last_answer="Not sure about that one.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="clarify",
            expected_action=CLARIFY_CURRENT_ANSWER,
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            consecutive_unusable=1,
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="thin_04_budget_advance",
            scenario="thin_answer",
            last_answer="I have no idea.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_context",
            expected_action="PROBE_FOR_CONTEXT",
            expected_competency_id="reliability",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            phase_index=2,
            consecutive_unusable=0,
            # Already had one "I don't know"; this second consecutive unknown advances
            # onto the next competency baseline (not another vague clarify).
            consecutive_explicit_unknown=1,
            allow_competency_change=True,
            must_not_cover=("establish_ownership", "applied_understanding"),
        ),
        RecordedSession(
            fixture_id="dodge_01_team_used",
            scenario="ownership_dodge",
            last_answer="The team used Redis because the project needed it.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            last_probe_shape="why",
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="dodge_02_group_effort",
            scenario="ownership_dodge",
            last_answer="It was a group effort on the billing service.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            last_probe_shape="failure_mode",
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="dodge_03_manager",
            scenario="ownership_dodge",
            last_answer="My manager decided and the team executed the plan.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            last_probe_shape="metric",
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="dodge_04_junior_bar",
            scenario="ownership_dodge",
            last_answer="We followed best practices and the team owned the rollout.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            profile_type="final_year_student",
            job_target_level="junior",
            last_probe_shape="trade_off",
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="metric_01_redis_ttl",
            scenario="metric_named",
            last_answer="I set Redis TTL to 200ms on the billing API.",
            asked_intent="establish_context",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            hook_stem="200ms",
        ),
        RecordedSession(
            fixture_id="metric_02_p99",
            scenario="metric_named",
            last_answer="I reduced p99 from 420ms to 90ms on the billing API.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="applied_understanding",
            expected_action="PROBE_FOR_METHOD",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            last_probe_shape="why",
            hook_stem="420ms",
        ),
        RecordedSession(
            fixture_id="metric_03_postgres",
            scenario="metric_named",
            last_answer="I chose Postgres over MySQL because writes were 95% append-only.",
            asked_intent="applied_understanding",
            competency_id="problem_solving",
            expected_intent="applied_understanding",
            expected_action="PROBE_FOR_METHOD",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context", "establish_ownership"),
            last_probe_shape="failure_mode",
            hook_stem="95%",
        ),
        RecordedSession(
            fixture_id="metric_04_worker_pool",
            scenario="metric_named",
            last_answer="I moved deserialization onto a worker pool and cut lag to 12ms on that work.",
            asked_intent="establish_context",
            competency_id="problem_solving",
            expected_intent="establish_context",
            expected_action="PROBE_FOR_CONTEXT",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            hook_stem="12ms",
        ),
        RecordedSession(
            fixture_id="contradiction_01_false_fact",
            scenario="contradiction",
            last_answer="I set Redis TTL to 200ms on the billing API.",
            asked_intent="establish_context",
            competency_id="problem_solving",
            expected_intent="establish_context",
            expected_action="PROBE_FOR_CONTEXT",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            factually_correct=False,
            must_not_cover=("establish_context", "establish_ownership"),
        ),
        RecordedSession(
            fixture_id="contradiction_02_deep_but_wrong",
            scenario="contradiction",
            last_answer="I reduced p99 from 420ms to 90ms on the billing API.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            factually_correct=False,
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="contradiction_03_off_topic",
            scenario="contradiction",
            last_answer="I prefer hiking on weekends when it rains in the hills.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="clarify",
            expected_action="CLARIFY_CURRENT_ANSWER",
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS,
            prior_candidate_turns=_DEFAULT_ANSWERS,
            pre_covered=("establish_context",),
            must_not_cover=("establish_ownership", "applied_understanding"),
            consecutive_unusable=0,
        ),
        RecordedSession(
            fixture_id="contradiction_04_stay_reliability",
            scenario="contradiction",
            last_answer="I handled the incident by turning TCP connectionless on the edge.",
            asked_intent="establish_ownership",
            competency_id="reliability",
            expected_intent="establish_ownership",
            expected_action="PROBE_FOR_OWNERSHIP",
            expected_competency_id="reliability",
            interviewer_turns=_DEFAULT_QUESTIONS
            + ("What incident were you dealing with?",),
            prior_candidate_turns=_DEFAULT_ANSWERS
            + ("We had a regional timeout on the edge proxy.",),
            pre_covered=("establish_context",),
            phase_index=3,
            factually_correct=False,
            must_not_cover=("establish_ownership",),
        ),
        RecordedSession(
            fixture_id="time_01_hard_close",
            scenario="time_up",
            last_answer="I owned the retries and reduced timeout errors on the API.",
            asked_intent="applied_understanding",
            competency_id="reliability",
            expected_intent="closing",
            expected_action=CLOSE_INTERVIEW,
            expected_competency_id="reliability",
            interviewer_turns=_DEFAULT_QUESTIONS * 3,
            prior_candidate_turns=_DEFAULT_ANSWERS * 3,
            pre_covered=("establish_context", "establish_ownership"),
            phase_index=3,
            elapsed_seconds=35 * 60 + 1,
            allow_competency_change=False,
        ),
        RecordedSession(
            fixture_id="time_02_soft_final",
            scenario="time_up",
            last_answer="I owned the retries and reduced timeout errors on the API.",
            asked_intent="applied_understanding",
            competency_id="reliability",
            expected_intent="final_addition",
            expected_action=OFFER_FINAL_ADDITION,
            expected_competency_id="reliability",
            interviewer_turns=_DEFAULT_QUESTIONS * 3,
            prior_candidate_turns=_DEFAULT_ANSWERS * 3,
            pre_covered=("establish_context", "establish_ownership"),
            phase_index=3,
            elapsed_seconds=27 * 60 + 5,
        ),
        RecordedSession(
            fixture_id="time_03_hard_from_problem_solving",
            scenario="time_up",
            last_answer="I built the retry worker and it mostly recovered timeouts.",
            asked_intent="establish_ownership",
            competency_id="problem_solving",
            expected_intent="closing",
            expected_action=CLOSE_INTERVIEW,
            expected_competency_id="problem_solving",
            interviewer_turns=_DEFAULT_QUESTIONS * 2,
            prior_candidate_turns=_DEFAULT_ANSWERS * 2,
            phase_index=2,
            elapsed_seconds=35 * 60 + 2,
        ),
        RecordedSession(
            fixture_id="time_04_target_close",
            scenario="time_up",
            last_answer="I owned the retries and reduced timeout errors on the API.",
            asked_intent="applied_understanding",
            competency_id="reliability",
            expected_intent="closing",
            expected_action=CLOSE_INTERVIEW,
            expected_competency_id="reliability",
            interviewer_turns=_DEFAULT_QUESTIONS * 3,
            prior_candidate_turns=_DEFAULT_ANSWERS * 3,
            pre_covered=("establish_context",),
            phase_index=3,
            elapsed_seconds=30 * 60 + 1,
        ),
    ]


def run_replay(session: RecordedSession) -> ReplayResult:
    definition = replay_definition()
    published_ids = [
        str(item.get("id"))
        for item in definition["competencies"]
        if item.get("id")
    ]
    phase_index = session.phase_index
    from products.interviewer.policy import outline_from_definition

    outline = outline_from_definition(definition) or {}
    if session.competency_id:
        for index, phase in enumerate(outline.get("phases") or []):
            if str(phase.get("competency_id") or "") == session.competency_id:
                phase_index = index
                break
    flow = InterviewFlow(
        {"phases": []},
        _UnusedLlm(),
        interview_definition=definition,
        job_description="Own Python services, incidents, and API reliability.",
        resume_text="Python backend work on billing retries.",
        candidate_profile={
            "job_target_level": session.job_target_level,
            "experience_summary": {"profile_type": session.profile_type},
            "claims": [
                {
                    "claim_id": "claim_project_1",
                    "type": "project",
                    "value": "Billing retries service",
                }
            ],
        },
        initial_phase_index=phase_index,
        initial_probe_count=session.probe_count,
        interviewer_turns=list(session.interviewer_turns),
        candidate_turns=list(session.prior_candidate_turns),
    )
    flow.last_question_intent = session.asked_intent
    flow.last_question_competency_id = session.competency_id
    flow.last_probe_shape[session.competency_id] = session.last_probe_shape
    flow.consecutive_unusable = session.consecutive_unusable
    flow.consecutive_explicit_unknown = session.consecutive_explicit_unknown
    flow.started_at = time.monotonic() - session.elapsed_seconds
    if session.pre_covered:
        apply_coverage(
            flow.coverage,
            competency_id=session.competency_id,
            covered_intents=list(session.pre_covered),
        )
    missing_before = list(
        (flow.coverage.get(session.competency_id) or {}).get("missing_intents") or []
    )
    answer_eval = None
    if session.factually_correct is False:
        answer_eval = AnswerEvaluation(
            technical_substance="partial",
            factually_correct=False,
            key_facts_stated=["contradicted published evidence"],
        )
    flow._record_answer_quality(
        session.last_answer,
        is_intro_reply=False,
        answer_eval=answer_eval,
    )
    decision = flow._current_policy_decision(
        pending_candidate_turn=True,
        advance_if_ready=True,
    )
    assert decision is not None
    entry = flow.coverage.get(session.competency_id) or {}
    fallback = flow._fallback_spoken_question(
        decision, last_turn=session.last_answer
    )
    return ReplayResult(
        fixture=session,
        decision=decision,
        missing_before=missing_before,
        missing_after=list(entry.get("missing_intents") or []),
        covered_after=list(entry.get("covered_intents") or []),
        published_ids=published_ids,
        fallback_question=fallback,
        hook_fact=extract_hook_fact(session.last_answer),
        next_shape=next_probe_shape(session.last_probe_shape),
    )


def score_followup_rubric(result: ReplayResult) -> RubricVerdict:
    """Apply the human follow-up rubric to one recorded session.

    This scores interviewer behavior (intent, hook, repetition, thin-answer
    handling). It does not invent candidate BARS scores.
    """
    notes: dict[str, str] = {}
    checks = {
        "logical": _check_logical(result, notes),
        "hooked": _check_hooked(result, notes),
        "non_repeating": _check_non_repeating(result, notes),
        "thin_answers": _check_thin_answers(result, notes),
        "accurate": _check_accurate(result, notes),
    }
    return RubricVerdict(
        fixture_id=result.fixture.fixture_id,
        passed=all(checks.values()),
        checks=checks,
        notes=notes,
    )


def _check_logical(result: ReplayResult, notes: dict[str, str]) -> bool:
    session = result.fixture
    decision = result.decision
    if (
        decision.competency_id
        and decision.competency_id not in result.published_ids
    ):
        notes["logical"] = "invented competency"
        return False
    if decision.action != session.expected_action:
        notes["logical"] = (
            f"action {decision.action} != {session.expected_action}"
        )
        return False
    if decision.intent != session.expected_intent:
        notes["logical"] = (
            f"intent {decision.intent} != {session.expected_intent}"
        )
        return False
    if (
        not session.allow_competency_change
        and decision.competency_id
        and decision.competency_id != session.expected_competency_id
    ):
        notes["logical"] = "left the active competency"
        return False
    if (
        decision.action not in _RECOVERY_ACTIONS
        and result.missing_after
        and not session.allow_competency_change
        and decision.intent != result.missing_after[0]
    ):
        notes["logical"] = "skipped first missing evidenced intent"
        return False
    if (
        session.allow_competency_change
        and decision.competency_id
        and decision.competency_id != session.competency_id
        and decision.competency_id != session.expected_competency_id
    ):
        notes["logical"] = "landed on unexpected competency after advance"
        return False
    notes["logical"] = "next intent matches the recorded plan"
    return True


def _check_hooked(result: ReplayResult, notes: dict[str, str]) -> bool:
    session = result.fixture
    if session.scenario != "metric_named":
        notes["hooked"] = "not applicable"
        return True
    # Hooks belong in LLM phrasing, not stock "You mentioned X" templates.
    # Replay proves the stem was extracted and available to the prompt.
    stem = (session.hook_stem or result.hook_fact or "").strip().lower()
    stems = hook_stem_tokens(session.hook_stem or result.hook_fact)
    extracted = (result.hook_fact or "").strip().lower()
    if stem and stem in extracted:
        notes["hooked"] = f"hook extracted for LLM: {stem}"
        return True
    if stems and any(token in extracted for token in stems):
        notes["hooked"] = "hook stem extracted for LLM"
        return True
    notes["hooked"] = "named metric/tool not extracted for the next turn"
    return False


def _check_non_repeating(result: ReplayResult, notes: dict[str, str]) -> bool:
    session = result.fixture
    if session.scenario in {"thin_answer", "time_up"}:
        notes["non_repeating"] = "not applicable"
        return True
    previous = prefix_tokens(session.interviewer_turns[-1])
    current = prefix_tokens(result.fallback_question)
    if len(previous) >= 6 and len(current) >= 6 and previous == current:
        notes["non_repeating"] = "repeated 6-word prefix"
        return False
    if (
        session.last_probe_shape
        and result.next_shape
        and result.next_shape == session.last_probe_shape
        and session.scenario == "metric_named"
    ):
        notes["non_repeating"] = "repeated probe_shape"
        return False
    notes["non_repeating"] = "prefix and probe_shape rotated"
    return True


def _check_thin_answers(result: ReplayResult, notes: dict[str, str]) -> bool:
    session = result.fixture
    if session.scenario != "thin_answer":
        notes["thin_answers"] = "not applicable"
        return True
    newly = set(result.covered_after) - set(session.pre_covered)
    if newly:
        notes["thin_answers"] = f"thin answer covered {sorted(newly)}"
        return False
    for intent in session.must_not_cover:
        if intent in result.covered_after:
            notes["thin_answers"] = f"{intent} marked covered"
            return False
    notes["thin_answers"] = "thin answer left intents missing"
    return True


def _check_accurate(result: ReplayResult, notes: dict[str, str]) -> bool:
    session = result.fixture
    if session.scenario != "contradiction":
        notes["accurate"] = "not applicable"
        return True
    if result.decision.competency_id != session.expected_competency_id:
        notes["accurate"] = "left competency after contradiction"
        return False
    newly = set(result.covered_after) - set(session.pre_covered)
    if newly:
        notes["accurate"] = f"contradiction covered {sorted(newly)}"
        return False
    notes["accurate"] = "stayed on competency; no invented score"
    return True
