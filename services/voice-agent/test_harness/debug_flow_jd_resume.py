#!/usr/bin/env python3
"""Debug structured interview flow with the sample JD + resume.

Uses a scripted LLM by default (no network). Pass --live only when OPENAI_API_KEY
(or the configured LLM) is available.

Examples:
  cd services/voice-agent
  PYTHONPATH=. python test_harness/debug_flow_jd_resume.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from products.interviewer.flow import InterviewFlow
from products.interviewer.policy import outline_from_definition

ROOT = Path(__file__).resolve().parent
SAMPLE_JD = (ROOT / "sample_jd.txt").read_text(encoding="utf-8").strip()
SAMPLE_RESUME = (ROOT / "sample_resume.txt").read_text(encoding="utf-8").strip()


def _definition() -> dict:
    return {
        "definition_id": "idef_flow_debug",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {"duration_minutes": 30},
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
            "What would you change if you did it again?",
        ],
        "job_intelligence": {
            "role": {"title": "Backend Engineer", "target_level": "mid"},
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
                            "Can you walk me through a production service you owned?"
                        ),
                    },
                    {
                        "depth": 2,
                        "intent": "establish_ownership",
                        "example_question": (
                            "What part of that service were you personally responsible for?"
                        ),
                    },
                ],
            }
        ],
    }


class ScriptedLlm:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def generate_reply(self, messages: list[dict]) -> str:
        _ = messages
        if not self.replies:
            return "{}"
        return self.replies.pop(0)


async def _run(scripted: bool) -> None:
    print("JD:", SAMPLE_JD)
    print("Resume:", SAMPLE_RESUME)
    definition = _definition()
    outline = outline_from_definition(definition)
    print("Outline phases:", [p.get("name") for p in (outline or {}).get("phases", [])])

    if scripted:
        llm: object = ScriptedLlm(
            [
                json.dumps(
                    {
                        "question": (
                            "What part of the FastAPI payments service "
                            "did you personally own?"
                        ),
                        "competency_id": "ownership",
                        "intent": "establish_ownership",
                        "depth": 2,
                        "answer_evaluation": {
                            "technical_substance": "surface",
                            "key_facts_stated": ["FastAPI payments service"],
                        },
                    }
                )
            ]
        )
    else:
        from clients.inference import get_llm_client

        llm = get_llm_client()

    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=definition,
        job_description=SAMPLE_JD,
        resume_text=SAMPLE_RESUME,
        allow_legacy_flow=False,
    )
    flow.phase_index = next(
        i for i, p in enumerate(flow.phases) if p.get("competency_id") == "ownership"
    )
    flow.candidate_turns = ["Hi, I'm Priya.", "I have five years of backend experience."]
    flow.interviewer_turns = [
        "Thanks for joining — please introduce yourself.",
        "Tell me about your background briefly.",
    ]
    flow.probe_count = 1
    flow.coverage["ownership"] = {
        "required_intents": [
            "establish_context",
            "establish_ownership",
            "applied_understanding",
        ],
        "covered_intents": ["establish_context"],
        "missing_intents": ["establish_ownership", "applied_understanding"],
    }
    decision = flow._current_policy_decision(pending_candidate_turn=True)
    print(
        "Policy:",
        None
        if decision is None
        else {
            "action": decision.action,
            "intent": decision.intent,
            "reason": decision.reason,
        },
    )
    question = await flow.generate_next_question(
        "We migrated a monolith to FastAPI services around payments."
    )
    print("Spoken question:", question)
    print(
        "Validator:",
        {
            "ok": flow.last_validator_ok,
            "reasons": flow.last_validator_reasons,
            "intent": flow.last_question_intent,
            "competency": flow.last_question_competency_id,
        },
    )
    if not question.endswith("?"):
        raise SystemExit("expected a spoken interview question")
    if flow.last_question_intent != "establish_ownership":
        raise SystemExit(
            f"expected establish_ownership follow-up, got {flow.last_question_intent}"
        )
    print("OK: sample JD/resume flow targeted ownership follow-up.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured live LLM instead of the scripted fixture.",
    )
    args = parser.parse_args()
    asyncio.run(_run(scripted=not args.live))


if __name__ == "__main__":
    main()
