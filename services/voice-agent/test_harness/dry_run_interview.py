#!/usr/bin/env python3
"""Multi-turn dry run of the AI interviewer with sample JD + resume.

Default uses OpenAI (live). Pass --scripted for offline fixture replies.

Examples:
  cd services/voice-agent
  set PYTHONPATH=.
  python test_harness/dry_run_interview.py
  python test_harness/dry_run_interview.py --turns 6
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from products.interviewer.flow import CLOSING_MESSAGE, InterviewFlow
from products.interviewer.policy import outline_from_definition

ROOT = Path(__file__).resolve().parent
SAMPLE_JD = (ROOT / "sample_jd.txt").read_text(encoding="utf-8").strip()
SAMPLE_RESUME = (ROOT / "sample_resume.txt").read_text(encoding="utf-8").strip()

# Candidate answers that exercise opening → context → ownership → method → dry → advance.
CANDIDATE_SCRIPT = [
    None,  # opening turn
    (
        "Hi, I'm Priya. I've been a backend engineer for about five years, "
        "mostly Python and FastAPI, and I was on-call for a payments API."
    ),
    (
        "We migrated a monolith into FastAPI services around payments. "
        "I worked on the payments API and the cutover."
    ),
    (
        "I personally owned the payments FastAPI service — routing, retries, "
        "and the Postgres schema for payment intents. Two juniors helped with "
        "tests; I owned design and on-call."
    ),
    (
        "For retries I used exponential backoff with idempotency keys in Redis "
        "so duplicate webhooks would not double-charge. We measured p95 latency "
        "and timeout errors before and after."
    ),
    "Yeah it was fine overall.",  # thin / dry follow-up fuel
    (
        "On reliability, the main failure mode was webhook storms. We rate-limited "
        "and added a dead-letter queue so operators could replay safely."
    ),
]


def _definition() -> dict:
    return {
        "definition_id": "idef_dry_run",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
            "allow_final_addition": True,
        },
        "non_answer_policy": {
            "clarify_after": 1,
            "rephrase_after": 2,
            "change_topic_after": 3,
            "confirm_continue_after": 4,
        },
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
            "What would you change if you did it again?",
        ],
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
                "max_depth": 4,
                "max_probes": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": [
                    "production ownership",
                    "personal contribution",
                    "technical approach",
                ],
            },
            {
                "id": "reliability",
                "name": "Reliability",
                "importance": "high",
                "max_depth": 3,
                "max_probes": 2,
                "min_assessment_intents": [
                    "establish_context",
                    "problem_or_complexity",
                ],
                "evidence_expected": ["incident handling", "failure mode"],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "ownership",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "objective": "Context of owned service",
                        "example_question": (
                            "Can you walk me through a production service you owned?"
                        ),
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "objective": "Personal ownership",
                        "example_question": (
                            "What part of that service were you personally responsible for?"
                        ),
                    },
                    {
                        "depth": 3,
                        "intent": "applied_understanding",
                        "objective": "How they built it",
                        "example_question": (
                            "How did you implement retries and avoid double charges?"
                        ),
                    },
                ],
            },
            {
                "competency_id": "reliability",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "objective": "Reliability context",
                        "example_question": (
                            "Tell me about a reliability issue you handled in production."
                        ),
                    },
                    {
                        "depth": 2,
                        "intent": "problem_or_complexity",
                        "objective": "Failure modes",
                        "example_question": (
                            "What made that failure hard to handle?"
                        ),
                    },
                ],
            },
        ],
    }


class ScriptedLlm:
    """Minimal offline replies so --scripted still exercises the loop."""

    def __init__(self) -> None:
        self._n = 0

    async def generate_reply(self, messages: list[dict]) -> str:
        _ = messages
        self._n += 1
        bank = [
            {
                "question": (
                    "Thanks for joining — looking at your FastAPI payments work, "
                    "please introduce yourself briefly."
                ),
                "competency_id": None,
                "intent": "opening",
                "depth": 1,
            },
            {
                "question": (
                    "Can you walk me through the production payments service "
                    "you owned during the migration?"
                ),
                "competency_id": "ownership",
                "intent": "establish_context",
                "depth": 1,
            },
            {
                "question": (
                    "What part of that FastAPI payments service were you "
                    "personally responsible for?"
                ),
                "competency_id": "ownership",
                "intent": "establish_ownership",
                "depth": 2,
            },
            {
                "question": (
                    "How did you implement retries so webhook duplicates "
                    "would not double-charge?"
                ),
                "competency_id": "ownership",
                "intent": "applied_understanding",
                "depth": 3,
            },
            {
                "question": "What was the measured outcome after that change?",
                "competency_id": "ownership",
                "intent": "applied_understanding",
                "depth": 3,
            },
            {
                "question": (
                    "Tell me about a reliability issue you handled on that "
                    "payments API."
                ),
                "competency_id": "reliability",
                "intent": "establish_context",
                "depth": 1,
            },
            {
                "question": "What made that failure mode hard to contain?",
                "competency_id": "reliability",
                "intent": "problem_or_complexity",
                "depth": 2,
            },
        ]
        payload = bank[min(self._n - 1, len(bank) - 1)]
        return json.dumps(payload)


def _print_turn(index: int, *, candidate: str | None, agent: str, flow: InterviewFlow) -> None:
    decision = flow.last_policy_decision
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
            "section": decision.section,
            "reason": decision.reason,
            "competency_id": decision.competency_id,
            "evidence_topic": decision.evidence_topic,
            "gap": decision.gap_kind,
            "probe_shape": decision.probe_shape,
        },
    )
    print(
        "VALIDATOR:",
        {
            "ok": flow.last_validator_ok,
            "reasons": flow.last_validator_reasons,
            "intent": flow.last_question_intent,
            "competency": flow.last_question_competency_id,
            "dry_probes": getattr(flow, "consecutive_dry_probes", None),
            "probe_count": flow.probe_count,
            "phase": (flow.current_phase() or {}).get("name"),
        },
    )
    # Compact coverage after each turn so dry-run debugging shows ladder progress.
    compact = {
        cid: {
            "status": entry.get("status"),
            "covered": entry.get("covered_intents"),
            "missing": entry.get("missing_intents"),
        }
        for cid, entry in (flow.coverage or {}).items()
    }
    print("COVERAGE:", json.dumps(compact, default=str))


async def _run(*, live: bool, turns: int) -> None:
    load_dotenv(ROOT.parent / ".env")
    definition = _definition()
    outline = outline_from_definition(definition)
    print("=== AI interviewer dry run ===")
    print("mode:", "live OpenAI" if live else "scripted")
    print("JD:", SAMPLE_JD)
    print("Resume:", SAMPLE_RESUME)
    print("Outline:", [p.get("name") for p in (outline or {}).get("phases", [])])

    if live:
        from clients.inference import get_llm_client

        llm: object = get_llm_client()
    else:
        llm = ScriptedLlm()

    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=definition,
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        allow_legacy_flow=False,
    )

    script = CANDIDATE_SCRIPT[: max(1, turns)]
    for index, candidate in enumerate(script, start=1):
        agent = await flow.generate_next_question(candidate)
        _print_turn(index, candidate=candidate, agent=agent, flow=flow)
        if agent == CLOSING_MESSAGE or "thank you for your time" in agent.lower():
            print("\nOK: interview reached closing.")
            return
        if not agent.strip():
            raise SystemExit(f"empty agent response on turn {index}")

    print("\nOK: dry run finished without closing (turn budget reached).")
    print("Coverage snapshot:", json.dumps(flow.coverage, indent=2, default=str)[:1200])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="Use offline scripted LLM instead of live OpenAI.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=6,
        help="Number of candidate turns including opening (default 6).",
    )
    args = parser.parse_args()
    asyncio.run(_run(live=not args.scripted, turns=args.turns))


if __name__ == "__main__":
    main()
