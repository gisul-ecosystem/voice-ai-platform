#!/usr/bin/env python3
"""Multi-case live dry runs — not the same sample JD/resume.

Cases:
  senior        — senior BE + deep distributed-systems answers
  sparse        — final-year / thin resume, still must hit JD bar
  nonanswer     — refuse / vague replies → clarify ladder / controlled close
  sales         — negotiation + strong method recovery after weak turns
  sales_strong  — positive-control method answer on first applied ask
  sales_weak    — weak-only path → applied must become assessed_insufficient

Examples:
  cd services/voice-agent
  set PYTHONPATH=.
  python test_harness/dry_run_cases.py
  python test_harness/dry_run_cases.py --case sparse --turns 5
  python test_harness/dry_run_cases.py --case sales --case sales_strong --case sales_weak
  python test_harness/dry_run_cases.py --case sales_strong --repeat 2
  python test_harness/dry_run_cases.py --all
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from products.interviewer.flow import CLOSING_MESSAGE, InterviewFlow
from products.interviewer.policy import outline_from_definition


@dataclass
class Case:
    name: str
    jd: str
    resume: str
    definition: dict[str, Any]
    answers: list[str | None]
    expect: dict[str, Any]


def _base_time_policy() -> dict[str, Any]:
    return {
        "duration_minutes": 30,
        "soft_end_minutes": 27,
        "target_end_minutes": 30,
        "hard_end_minutes": 35,
        "allow_final_addition": True,
    }


def _non_answer_policy() -> dict[str, Any]:
    return {
        "clarify_after": 1,
        "rephrase_after": 2,
        "change_topic_after": 3,
        "confirm_continue_after": 4,
    }


def case_senior() -> Case:
    return Case(
        name="senior",
        jd=(
            "Senior Backend Engineer. 8+ years. Distributed systems, event-driven "
            "architecture, Kafka, Postgres, ownership of multi-region services, "
            "mentoring, incident command."
        ),
        resume=(
            "Alex R. 10 years backend. Led multi-region checkout platform. "
            "Kafka, Postgres, Go/Python. Incident commander for SEV1s. Mentored 6 engineers."
        ),
        definition={
            "definition_id": "idef_senior",
            "prompt_version": "interviewer-system-v2",
            "time_policy": _base_time_policy(),
            "non_answer_policy": _non_answer_policy(),
            "job_intelligence": {
                "role": {
                    "title": "Senior Backend Engineer",
                    "target_level": "senior",
                    "domain": "software",
                }
            },
            "competencies": [
                {
                    "id": "distributed_systems",
                    "name": "Distributed systems",
                    "importance": "high",
                    "max_depth": 4,
                    "max_probes": 3,
                    "min_assessment_intents": [
                        "establish_context",
                        "establish_ownership",
                        "applied_understanding",
                        "problem_or_complexity",
                    ],
                    "evidence_expected": [
                        "multi-region design",
                        "personal ownership",
                        "failure handling",
                    ],
                }
            ],
            "question_ladders": [
                {
                    "competency_id": "distributed_systems",
                    "levels": [
                        {
                            "depth": 1,
                            "intent": "establish_context",
                            "example_question": (
                                "Walk me through a multi-region service you owned."
                            ),
                        },
                        {
                            "depth": 2,
                            "intent": "establish_ownership",
                            "example_question": (
                                "What part of that platform were you personally accountable for?"
                            ),
                        },
                        {
                            "depth": 3,
                            "intent": "applied_understanding",
                            "example_question": (
                                "How did you handle cross-region consistency?"
                            ),
                        },
                        {
                            "depth": 4,
                            "intent": "problem_or_complexity",
                            "example_question": (
                                "What failure mode was hardest in production?"
                            ),
                        },
                    ],
                }
            ],
        },
        answers=[
            None,
            (
                "I'm Alex, ten years in backend. I led a multi-region checkout "
                "platform with Kafka and Postgres and ran SEV1 incident command."
            ),
            (
                "Checkout spanned three regions. I owned the order-service and "
                "the Kafka outbox path for payment events."
            ),
            (
                "I personally owned the outbox publisher and the consumer "
                "idempotency contract — the team owned UI; I owned the event path."
            ),
            (
                "We used an outbox table plus Kafka with idempotency keys per "
                "order_id so a region failover wouldn't double-charge. Measured "
                "duplicate-publish rate before and after."
            ),
            (
                "Hardest failure was a split-brain during region drain — consumers "
                "replayed old offsets. We added fence tokens and a dead-letter topic."
            ),
        ],
        expect={
            "min_validator_ok_ratio": 0.8,
            "must_enter_competency": "distributed_systems",
            "prefer_covered_any": [
                "establish_context",
                "establish_ownership",
                "applied_understanding",
            ],
        },
    )


def case_sparse() -> Case:
    return Case(
        name="sparse",
        jd=(
            "Backend engineer (Python). FastAPI production services, ownership, "
            "basic reliability. Internships welcome but bar is applied work."
        ),
        resume=(
            "Sam K. Final-year BCA student. Internship: built a FastAPI todo API "
            "with Postgres. Course projects only. No on-call experience."
        ),
        definition={
            "definition_id": "idef_sparse",
            "prompt_version": "interviewer-system-v2",
            "time_policy": _base_time_policy(),
            "non_answer_policy": _non_answer_policy(),
            "job_intelligence": {
                "role": {
                    "title": "Backend Engineer",
                    "target_level": "mid",
                    "domain": "software",
                }
            },
            "competencies": [
                {
                    "id": "ownership",
                    "name": "Service ownership",
                    "importance": "high",
                    "max_depth": 3,
                    "max_probes": 3,
                    "min_assessment_intents": [
                        "establish_context",
                        "establish_ownership",
                        "applied_understanding",
                    ],
                    "evidence_expected": [
                        "personal contribution",
                        "technical approach",
                    ],
                }
            ],
            "question_ladders": [
                {
                    "competency_id": "ownership",
                    "levels": [
                        {
                            "depth": 1,
                            "intent": "establish_context",
                            "example_question": (
                                "Tell me about a service or API you worked on."
                            ),
                        },
                        {
                            "depth": 2,
                            "intent": "establish_ownership",
                            "example_question": (
                                "What part did you personally implement?"
                            ),
                        },
                        {
                            "depth": 3,
                            "intent": "applied_understanding",
                            "example_question": (
                                "How did you store and fetch data in that API?"
                            ),
                        },
                    ],
                }
            ],
        },
        answers=[
            None,
            (
                "Hi, I'm Sam, final-year BCA. I did an internship where I built a "
                "FastAPI todo API with Postgres."
            ),
            (
                "It was a small todo API for the internship team — create/list "
                "tasks backed by Postgres."
            ),
            (
                "I owned the FastAPI routes and the SQLAlchemy models. My mentor "
                "reviewed PRs; I wrote the endpoints."
            ),
            (
                "I used SQLAlchemy with Postgres, pagination on list, and simple "
                "indexes on user_id. We checked query time in logs."
            ),
        ],
        expect={
            "min_validator_ok_ratio": 0.75,
            "must_enter_competency": "ownership",
            "opening_must_not_invent_claims": True,
            "prefer_covered_any": ["establish_context", "establish_ownership"],
        },
    )


def case_nonanswer() -> Case:
    return Case(
        name="nonanswer",
        jd="Backend engineer. Ownership of production APIs.",
        resume="Jordan. 3 years Python backend. Built internal tools.",
        definition={
            "definition_id": "idef_nonanswer",
            "prompt_version": "interviewer-system-v2",
            "time_policy": _base_time_policy(),
            "non_answer_policy": _non_answer_policy(),
            "job_intelligence": {
                "role": {
                    "title": "Backend Engineer",
                    "target_level": "mid",
                    "domain": "software",
                }
            },
            "competencies": [
                {
                    "id": "ownership",
                    "name": "Service ownership",
                    "importance": "high",
                    "max_depth": 3,
                    "max_probes": 2,
                    "min_assessment_intents": [
                        "establish_context",
                        "establish_ownership",
                    ],
                    "evidence_expected": ["personal contribution"],
                }
            ],
            "question_ladders": [
                {
                    "competency_id": "ownership",
                    "levels": [
                        {
                            "depth": 1,
                            "intent": "establish_context",
                            "example_question": "Tell me about a service you owned.",
                        },
                        {
                            "depth": 2,
                            "intent": "establish_ownership",
                            "example_question": "What did you personally own?",
                        },
                    ],
                }
            ],
        },
        answers=[
            None,
            "Hi, I'm Jordan.",
            "I don't know.",
            "Not sure.",
            "Pass.",
            "I can't answer that.",
            "Still nothing.",
        ],
        expect={
            "allow_closing": True,
            "min_validator_ok_ratio": 0.5,
            "expect_unusable_path": True,
        },
    )


def case_sales() -> Case:
    """Borderline method answer, then +2 turns including a strong method control.

    Turn 5 keeps the original thin 'traded…' answer (known not to hit method cues).
    Turns 6–7 give further chances; turn 7 is a deliberate positive-control method
    answer so we can tell 'weak answer' apart from 'sales domain never credits applied'.
    """
    return Case(
        name="sales",
        jd=(
            "Enterprise Account Executive. Pipeline ownership, negotiation, "
            "multi-stakeholder deals, CRM hygiene."
        ),
        resume=(
            "Taylor M. 6 years B2B sales. Closed $2M ARR SaaS deals. "
            "Salesforce, MEDDIC, negotiated procurement and legal."
        ),
        definition={
            "definition_id": "idef_sales",
            "prompt_version": "interviewer-system-v2",
            "time_policy": _base_time_policy(),
            "non_answer_policy": _non_answer_policy(),
            "job_intelligence": {
                "role": {
                    "title": "Account Executive",
                    "target_level": "mid",
                    "domain": "sales",
                }
            },
            "competencies": [
                {
                    "id": "negotiation",
                    "name": "Negotiation",
                    "importance": "high",
                    "max_depth": 4,
                    "max_probes": 6,
                    "min_assessment_intents": [
                        "establish_context",
                        "establish_ownership",
                        "applied_understanding",
                    ],
                    "evidence_expected": [
                        "deal context",
                        "personal role",
                        "negotiation approach",
                    ],
                }
            ],
            "question_ladders": [
                {
                    "competency_id": "negotiation",
                    "levels": [
                        {
                            "depth": 1,
                            "intent": "establish_context",
                            "example_question": (
                                "Tell me about a complex deal you negotiated."
                            ),
                        },
                        {
                            "depth": 2,
                            "intent": "establish_ownership",
                            "example_question": (
                                "What parts of that negotiation did you own?"
                            ),
                        },
                        {
                            "depth": 3,
                            "intent": "applied_understanding",
                            "example_question": (
                                "How did you handle a pricing or legal stalemate?"
                            ),
                        },
                    ],
                }
            ],
        },
        answers=[
            None,
            (
                "I'm Taylor, six years in B2B SaaS sales. I closed about two "
                "million ARR using MEDDIC and Salesforce."
            ),
            (
                "One deal was a manufacturing customer with procurement and legal "
                "blocking on liability caps."
            ),
            (
                "I owned the commercial negotiation and stakeholder map; my SE "
                "owned the demo. I ran the procurement calls."
            ),
            # Borderline — outcome language, no method cues (known miss).
            (
                "I traded a shorter pilot for a lower liability cap, documented "
                "concessions in Salesforce, and closed in two weeks."
            ),
            # Second chance still thin.
            (
                "Yeah, that trade closed the deal. Procurement signed after we "
                "agreed on the pilot length."
            ),
            # Positive-control method/reasoning language for sales domain.
            (
                "I used a give-get approach. I chose a shorter pilot instead of a "
                "bigger discount because procurement cared more about liability "
                "exposure, and we used Salesforce to document each concession "
                "step by step."
            ),
        ],
        expect={
            "min_validator_ok_ratio": 0.75,
            "must_enter_competency": "negotiation",
            "require_covered_all": [
                "establish_context",
                "establish_ownership",
                "applied_understanding",
            ],
            "require_coverage_complete": True,
            "require_clean_hooks": True,
            "forbid_tech_trivia": True,
            "track_applied_understanding": True,
        },
    )


def case_sales_strong() -> Case:
    """Positive control: first applied answer already has clear method cues."""
    base = case_sales()
    return Case(
        name="sales_strong",
        jd=base.jd,
        resume=base.resume,
        definition=base.definition,
        answers=[
            None,
            (
                "I'm Taylor, six years in B2B SaaS sales. I closed about two "
                "million ARR using MEDDIC and Salesforce."
            ),
            (
                "One deal was a manufacturing customer with procurement and legal "
                "blocking on liability caps."
            ),
            (
                "I owned the commercial negotiation and stakeholder map; my SE "
                "owned the demo. I ran the procurement calls."
            ),
            (
                "I used a give-get approach. I chose a shorter pilot instead of a "
                "bigger discount because procurement cared more about liability "
                "exposure, and we used Salesforce to document each concession "
                "step by step."
            ),
        ],
        expect={
            "min_validator_ok_ratio": 0.75,
            "must_enter_competency": "negotiation",
            "require_covered_all": [
                "establish_context",
                "establish_ownership",
                "applied_understanding",
            ],
            "require_coverage_complete": True,
            "require_clean_hooks": True,
            "forbid_tech_trivia": True,
            "track_applied_understanding": True,
            "require_applied_covered": True,
        },
    )


def case_sales_weak() -> Case:
    """Pure negative: weak method answers only — applied must not stay stuck at asked.

    After soft-close / leave, ``applied_understanding`` should become
    ``assessed_insufficient`` (not remaining ``asked`` forever).
    """
    base = case_sales()
    definition = dict(base.definition)
    definition["definition_id"] = "idef_sales_weak"
    # Exhaust probes quickly so soft-close is reachable without a strong answer.
    comps = []
    for row in definition.get("competencies") or []:
        item = dict(row)
        if item.get("id") == "negotiation":
            item["max_probes"] = 3
            item["max_depth"] = 3
        comps.append(item)
    definition["competencies"] = comps
    return Case(
        name="sales_weak",
        jd=base.jd,
        resume=base.resume,
        definition=definition,
        answers=[
            None,
            (
                "I'm Taylor, six years in B2B SaaS sales. I closed about two "
                "million ARR using MEDDIC and Salesforce."
            ),
            (
                "One deal was a manufacturing customer with procurement and legal "
                "blocking on liability caps."
            ),
            (
                "I owned the commercial negotiation and stakeholder map; my SE "
                "owned the demo. I ran the procurement calls."
            ),
            (
                "I traded a shorter pilot for a lower liability cap, documented "
                "concessions in Salesforce, and closed in two weeks."
            ),
            (
                "Yeah, that trade closed the deal. Procurement signed after we "
                "agreed on the pilot length."
            ),
            (
                "Nothing more to add — that was basically it."
            ),
        ],
        expect={
            "min_validator_ok_ratio": 0.5,
            "must_enter_competency": "negotiation",
            "require_clean_hooks": True,
            "forbid_tech_trivia": True,
            "track_applied_understanding": True,
            "require_assessed_insufficient": ["applied_understanding"],
            # Must not end stuck only at asked after close.
            "forbid_applied_stuck_asked": True,
        },
    )


CASES = {
    "senior": case_senior,
    "sparse": case_sparse,
    "nonanswer": case_nonanswer,
    "sales": case_sales,
    "sales_strong": case_sales_strong,
    "sales_weak": case_sales_weak,
}


def _print_turn(index: int, *, candidate: str | None, agent: str, flow: InterviewFlow) -> None:
    from products.interviewer.coverage import (
        _METHOD_CUES,
        _TRADEOFF_CUES,
        evidenced_intents,
        required_intents_for,
    )

    decision = flow.last_policy_decision
    compact = {
        cid: {
            "status": entry.get("status"),
            "covered": entry.get("covered_intents"),
            "missing": entry.get("missing_intents"),
            "intent_status": entry.get("intent_status"),
        }
        for cid, entry in (flow.coverage or {}).items()
    }
    print()
    print(f"======== TURN {index} ========")
    print("CANDIDATE:", "(opening)" if candidate is None else candidate)
    print("AGENT:", agent)
    print(
        "POLICY:",
        None
        if decision is None
        else {
            "action": decision.action,
            "intent": decision.intent,
            "reason": decision.reason,
            "competency_id": decision.competency_id,
        },
    )
    print(
        "VALIDATOR:",
        {
            "ok": flow.last_validator_ok,
            "reasons": flow.last_validator_reasons,
            "intent": flow.last_question_intent,
            "competency": flow.last_question_competency_id,
            "phase": (flow.current_phase() or {}).get("name"),
        },
    )
    print("COVERAGE:", json.dumps(compact, default=str))
    if candidate and flow.last_question_competency_id:
        required = required_intents_for(
            flow.interview_definition, flow.last_question_competency_id
        )
        # Cue path only — mirrors what would credit without relying on LLM judge.
        cue_covered = evidenced_intents(
            required_intents=required,
            evidence_expected=[],
            answer_eval=None,
            asked_intent="applied_understanding",
            answer_text=candidate,
        )
        lowered = f" {candidate.lower()} "
        print(
            "CUE_DIAG:",
            json.dumps(
                {
                    "keyword_evidenced_if_asked_applied": cue_covered,
                    "method_cues_hit": [c for c in _METHOD_CUES if c in lowered],
                    "tradeoff_cues_hit": [c for c in _TRADEOFF_CUES if c in lowered],
                    "applied_status_now": (
                        (compact.get(str(flow.last_question_competency_id)) or {}).get(
                            "intent_status"
                        )
                        or {}
                    ).get("applied_understanding"),
                },
                default=str,
            ),
        )


def _evaluate(case: Case, flow: InterviewFlow, validator_flags: list[bool]) -> dict[str, Any]:
    ok_ratio = (
        sum(1 for flag in validator_flags if flag is True) / len(validator_flags)
        if validator_flags
        else 0.0
    )
    report: dict[str, Any] = {
        "case": case.name,
        "validator_ok_ratio": round(ok_ratio, 2),
        "phase": (flow.current_phase() or {}).get("name"),
        "coverage": {
            cid: {
                "status": entry.get("status"),
                "covered": entry.get("covered_intents"),
                "intent_status": entry.get("intent_status"),
            }
            for cid, entry in (flow.coverage or {}).items()
        },
        "checks": {},
    }
    checks = report["checks"]
    expect = case.expect

    min_ratio = float(expect.get("min_validator_ok_ratio") or 0.0)
    checks["validator_ok_ratio"] = ok_ratio >= min_ratio

    must_comp = expect.get("must_enter_competency")
    if must_comp:
        entry = (flow.coverage or {}).get(str(must_comp)) or {}
        asked_or_covered = any(
            status in {"asked", "covered", "assessed_insufficient"}
            for status in (entry.get("intent_status") or {}).values()
        ) or bool(entry.get("covered_intents"))
        # Also pass if we at least asked questions while on that competency phase.
        checks["entered_competency"] = asked_or_covered or any(
            str(must_comp) in str(flow.last_question_competency_id or "")
            for _ in [0]
        ) or any(
            (entry.get("intent_status") or {})
            for entry in (flow.coverage or {}).values()
        )
        # Stronger: any intent_status not all-absent on that competency.
        statuses = list((entry.get("intent_status") or {}).values())
        checks["entered_competency"] = bool(statuses) and any(
            value != "absent" for value in statuses
        ) or bool(entry.get("covered_intents"))

    prefer = list(expect.get("prefer_covered_any") or [])
    if prefer and must_comp:
        covered = set(((flow.coverage or {}).get(str(must_comp)) or {}).get("covered_intents") or [])
        checks["prefer_covered_any"] = bool(covered.intersection(prefer))

    if expect.get("expect_unusable_path"):
        checks["unusable_or_closing"] = (
            flow.consecutive_unusable >= 1
            or flow.completed
            or (
                flow.last_policy_decision
                and flow.last_policy_decision.intent
                in {
                    "clarify",
                    "closing",
                    "recovery",
                    "final_addition",
                }
            )
        )

    require_all = list(expect.get("require_covered_all") or [])
    if require_all and must_comp:
        covered = set(((flow.coverage or {}).get(str(must_comp)) or {}).get("covered_intents") or [])
        checks["require_covered_all"] = set(require_all).issubset(covered)

    if expect.get("require_coverage_complete") and must_comp:
        entry = (flow.coverage or {}).get(str(must_comp)) or {}
        checks["coverage_complete"] = entry.get("status") == "complete"

    if expect.get("forbid_tech_trivia"):
        # Soft check: no acronym-drill style in last spoken question.
        last_q = (flow.interviewer_turns or [""])[-1].lower()
        checks["no_tech_trivia"] = not any(
            marker in last_q
            for marker in ("stand for", "full form", "brain teaser", "riddle")
        )

    if expect.get("require_applied_covered") and must_comp:
        status = (
            ((flow.coverage or {}).get(str(must_comp)) or {}).get("intent_status") or {}
        ).get("applied_understanding")
        checks["applied_understanding_covered"] = status == "covered"

    if expect.get("track_applied_understanding") and must_comp:
        status = (
            ((flow.coverage or {}).get(str(must_comp)) or {}).get("intent_status") or {}
        ).get("applied_understanding")
        report["applied_understanding_final"] = status

    insufficient = list(expect.get("require_assessed_insufficient") or [])
    if insufficient and must_comp:
        status_map = (
            ((flow.coverage or {}).get(str(must_comp)) or {}).get("intent_status") or {}
        )
        checks["assessed_insufficient"] = all(
            status_map.get(intent) == "assessed_insufficient" for intent in insufficient
        )

    if expect.get("forbid_applied_stuck_asked") and must_comp:
        status = (
            ((flow.coverage or {}).get(str(must_comp)) or {}).get("intent_status") or {}
        ).get("applied_understanding")
        checks["applied_not_stuck_asked"] = status != "asked"

    hooks = list(getattr(flow, "_harness_hooks", None) or [])
    report["hooks_seen"] = hooks
    if expect.get("require_clean_hooks"):
        from products.interviewer.validator import is_clean_hook_fact

        # Empty hooks (opening/map) are fine; non-empty must be clean phrases.
        checks["clean_hooks"] = all(is_clean_hook_fact(hook) for hook in hooks)

    report["pass"] = all(checks.values()) if checks else True
    return report


async def _run_case(case: Case, *, turns: int | None) -> dict[str, Any]:
    load_dotenv()
    from clients.inference import get_llm_client
    from products.interviewer.validator import SKIP_HOOK_INTENTS, is_clean_hook_fact

    print()
    print("#" * 72)
    print(f"# CASE: {case.name}")
    print("#" * 72)
    print("JD:", case.jd)
    print("Resume:", case.resume)
    outline = outline_from_definition(case.definition)
    print("Outline:", [p.get("name") for p in (outline or {}).get("phases", [])])

    flow = InterviewFlow(
        {"phases": []},
        get_llm_client(),
        interview_definition=case.definition,
        job_description=case.jd,
        resume_text=case.resume,
        allow_legacy_flow=False,
        candidate_profile={
            "experience_summary": {
                "profile_type": (
                    "final_year_student" if case.name == "sparse" else "experienced"
                )
            }
        },
    )
    flow._harness_hooks = []  # type: ignore[attr-defined]

    script = list(case.answers)
    if turns is not None:
        script = script[: max(1, turns)]

    validator_flags: list[bool] = []
    for index, candidate in enumerate(script, start=1):
        agent = await flow.generate_next_question(candidate)
        hook = getattr(flow, "last_hook_fact", "") or ""
        if hook and (flow.last_question_intent or "") not in SKIP_HOOK_INTENTS:
            flow._harness_hooks.append(hook)  # type: ignore[attr-defined]
            print(
                "HOOK:",
                json.dumps(
                    {"fact": hook, "clean": is_clean_hook_fact(hook)},
                    default=str,
                ),
            )
        _print_turn(index, candidate=candidate, agent=agent, flow=flow)
        if flow.last_validator_ok is not None:
            validator_flags.append(bool(flow.last_validator_ok))
        if agent == CLOSING_MESSAGE or "thank you for your time" in agent.lower():
            print("\nReached closing.")
            break
        if not agent.strip():
            raise SystemExit(f"{case.name}: empty agent on turn {index}")

    report = _evaluate(case, flow, validator_flags)
    print()
    print("CASE_REPORT:", json.dumps(report, indent=2, default=str))
    return report


async def _main(names: list[str], turns: int | None, repeat: int) -> None:
    reports: list[dict[str, Any]] = []
    for name in names:
        factory = CASES[name]
        run_reports: list[dict[str, Any]] = []
        for run_index in range(max(1, repeat)):
            if repeat > 1:
                print()
                print(f"### REPEAT {run_index + 1}/{repeat} — {name}")
            run_reports.append(await _run_case(factory(), turns=turns))
        if repeat > 1:
            _assert_repeat_stable(name, run_reports)
        reports.append(run_reports[-1])
    print()
    print("=" * 72)
    print("SUMMARY")
    for report in reports:
        status = "PASS" if report.get("pass") else "FAIL"
        print(
            f"- {report['case']}: {status} "
            f"(validator_ok_ratio={report.get('validator_ok_ratio')})"
        )
    failed = [report["case"] for report in reports if not report.get("pass")]
    if failed:
        raise SystemExit(f"failed cases: {', '.join(failed)}")
    print("All selected cases passed gates.")


def _coverage_fingerprint(report: dict[str, Any]) -> dict[str, Any]:
    """Stable slice for live determinism diffs (ignore validator ratio noise)."""
    return {
        "coverage": report.get("coverage"),
        "applied_understanding_final": report.get("applied_understanding_final"),
        "phase": report.get("phase"),
    }


def _assert_repeat_stable(name: str, run_reports: list[dict[str, Any]]) -> None:
    """Fail when live repeats disagree on coverage / intent_status."""
    fingerprints = [_coverage_fingerprint(report) for report in run_reports]
    first = fingerprints[0]
    diverged = [
        index
        for index, fingerprint in enumerate(fingerprints[1:], start=2)
        if fingerprint != first
    ]
    print()
    print("DETERMINISM:", json.dumps({"case": name, "runs": len(run_reports)}, default=str))
    if not diverged:
        print(f"DETERMINISM: {name} — coverage fingerprint identical across {len(run_reports)} runs")
        return
    print("DETERMINISM_DIVERGENCE:")
    print(json.dumps({"run_1": first, "later": fingerprints[1:]}, indent=2, default=str))
    raise SystemExit(
        f"{name}: live coverage fingerprint diverged on runs {diverged} "
        "(same fixture, live OpenAI — non-determinism still present)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=sorted(CASES),
        action="append",
        help="Case to run (repeatable). Default: all.",
    )
    parser.add_argument("--all", action="store_true", help="Run every case.")
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Optional turn cap per case.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "Run each selected case N times and fail if coverage/intent_status "
            "fingerprints diverge (live OpenAI determinism check)."
        ),
    )
    args = parser.parse_args()
    names = sorted(CASES) if args.all or not args.case else list(dict.fromkeys(args.case))
    asyncio.run(_main(names, args.turns, max(1, int(args.repeat or 1))))

if __name__ == "__main__":
    main()
