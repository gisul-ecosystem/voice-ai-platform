"""Score follow-up targets on the sample interview script. No LLM."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dry_run_interview import CANDIDATE_SCRIPT, _definition
from products.interviewer.flow import InterviewFlow


class _Silent:
    async def generate_reply(self, messages: list[dict]) -> str:
        return "{}"


def walk() -> list[dict]:
    flow = InterviewFlow(
        {"phases": []},
        _Silent(),
        interview_definition=_definition(),
        job_description="Backend engineer owning payments APIs.",
        resume_text="Priya, FastAPI payments service.",
    )
    rows: list[dict] = []
    for index, answer in enumerate(CANDIDATE_SCRIPT):
        if answer:
            flow._record_answer_quality(
                answer, is_intro_reply=not flow.candidate_turns
            )
        decision = flow._current_policy_decision(
            pending_candidate_turn=bool(answer),
            advance_if_ready=True,
        )
        assert decision is not None
        prompt, _ = flow._structured_system_prompt(answer, decision)
        topic_line = next(
            (
                line
                for line in prompt.splitlines()
                if line.startswith("Evidence still missing")
            ),
            "",
        )
        entry = flow.coverage.get(decision.competency_id or "", {})
        rows.append(
            {
                "turn": index,
                "phase": flow.current_phase().get("name"),
                "action": decision.action,
                "intent": decision.intent,
                "topic": decision.evidence_topic,
                "gap": decision.gap_kind,
                "shape": decision.probe_shape,
                "basis": decision.basis,
                "missing": list(entry.get("missing_intents") or []),
                "covered": list(entry.get("covered_intents") or []),
                "topic_line": topic_line,
                "flow": decision.forced_flow_decision,
            }
        )
        if answer:
            flow.candidate_turns.append(answer)
            flow._apply_turn_decision(
                decision.forced_flow_decision,
                is_intro_reply=len(flow.candidate_turns) == 1,
            )
        flow.interviewer_turns.append("q")
        if decision.intent not in {"clarify", "rephrase"}:
            flow.last_question_intent = decision.intent
        if decision.competency_id and decision.probe_shape:
            flow.last_probe_shape[decision.competency_id] = decision.probe_shape
    return rows


def main() -> None:
    for row in walk():
        print(
            f"TURN {row['turn']} {row['phase']} {row['action']} "
            f"intent={row['intent']} topic={row['topic']!r} gap={row['gap']} "
            f"shape={row['shape']} flow={row['flow']}"
        )
        print(f"  missing={row['missing']} covered={row['covered']}")
        print(f"  {row['topic_line']}")
        print(f"  {row['basis']}")


if __name__ == "__main__":
    main()
