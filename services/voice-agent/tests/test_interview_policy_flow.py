"""InterviewFlow policy-mode integration tests."""
from __future__ import annotations

import asyncio

import pytest

from products.interviewer.flow import InterviewFlow


class FakeLlm:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict]] = []

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.messages.append(messages)
        return self.replies.pop(0)


def _definition() -> dict:
    return {
        "definition_id": "idef_flow_policy_01",
        "prompt_version": "interviewer-system-v2",
        "time_policy": {
            "duration_minutes": 30,
            "soft_end_minutes": 27,
            "target_end_minutes": 30,
            "hard_end_minutes": 35,
        },
        "competencies": [
            {
                "id": "problem_solving",
                "name": "Problem solving",
                "max_depth": 3,
                "max_probes": 2,
                "evidence_expected": ["context", "ownership", "result"],
            },
            {
                "id": "communication",
                "name": "Communication",
                "max_depth": 3,
                "max_probes": 2,
                "evidence_expected": ["clarity"],
            },
        ],
        "question_ladders": [
            {
                "competency_id": "problem_solving",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "example_question": "Which algorithm did you use for that problem?",
                    },
                ],
            },
        ],
    }


def test_policy_prompt_contains_full_technical_reference_context() -> None:
    definition = _definition()
    definition["job_intelligence"] = {
        "role": {"title": "AI Engineer", "domain": "AI/ML", "target_level": "mid"},
        "knowledge": [{"text": "Model evaluation and overfitting"}],
        "skills": [{"text": "Python and machine learning"}],
        "tools": [{"text": "scikit-learn"}],
        "raw_job_description": "Use algorithms, data structures, and model evaluation.",
    }
    definition["question_ladders"].append(
        {
            "competency_id": "communication",
            "levels": [
                {
                    "depth": 1,
                    "intent": "establish_context",
                    "objective": "Assess technical communication",
                    "example_question": "How would you explain a model trade-off?",
                }
            ],
        }
    )
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=definition,
        job_description="Use algorithms, data structures, and model evaluation.",
        resume_text="Built a machine learning classifier in Python.",
        candidate_profile={"claims": [{"claim_id": "c1", "value": "Built a machine learning classifier"}]},
        initial_phase_index=2,
    )

    prompt, _ = flow._structured_system_prompt(
        "I built a machine learning classifier in Python.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )

    assert "machine learning" in prompt.lower()
    assert "data structures" in prompt.lower()
    assert "model evaluation" in prompt.lower()
    assert "technical communication" not in prompt.lower()
    assert "example:" not in prompt.lower()


@pytest.mark.asyncio
async def test_policy_mode_blocks_immediate_deep_dive_advance() -> None:
    llm = FakeLlm(
        '{"question":"When did you work on payments, and for whom?",'
        '"competency_id":"problem_solving","intent":"establish_context","depth":1,'
        '"probe_shape":"why"}'
    )
    flow = InterviewFlow(
        {"phases": [{"name": "legacy", "duration_minutes": 10, "topics": ["x"], "source": "generic"}]},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["Thanks for joining. Please introduce yourself."],
        candidate_turns=[],
        initial_phase_index=1,
    )
    assert flow.policy_mode is True
    assert flow.phases[0]["name"] == "opening"

    question = await flow.generate_next_question(
        "I am a backend engineer who worked on payments."
    )
    prompt = llm.messages[0][0]["content"]
    assert "POLICY ENGINE" in prompt
    # candidate_map's forced advance is resolved before the prompt is built, so the
    # LLM sees the real next competency it is entering, not the phase it just left.
    assert "Problem solving" in prompt
    assert "problem_solving" in prompt
    # Forced probe — cannot honor LLM advance into deep dive.
    assert flow.phase_index == 2
    assert question == "When did you work on payments, and for whom?"
    assert "Which algorithm did you use" not in question


@pytest.mark.asyncio
async def test_policy_mode_speaks_valid_llm_question_not_ladder() -> None:
    llm = FakeLlm(
        '{"question":"What graph problem did you solve?",'
        '"competency_id":"problem_solving","intent":"establish_context","depth":1,'
        '"probe_shape":"why"}'
    )
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )

    question = await flow.generate_next_question("I solved a graph problem.")

    assert question == "What graph problem did you solve?"
    assert "Which algorithm did you use" not in question


@pytest.mark.asyncio
async def test_policy_mode_falls_back_to_ladder_when_json_is_invalid() -> None:
    llm = FakeLlm("not-json", "still-not-json")
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )

    question = await flow.generate_next_question("I solved a graph problem.")

    assert "Which algorithm did you use" in question
    assert "You mentioned" not in question
    assert not question.lower().startswith("regarding ")


@pytest.mark.asyncio
async def test_policy_mode_advances_after_probe_cap() -> None:
    llm = FakeLlm(
        '{"question":"What broke when the billing API timed out?",'
        '"competency_id":"problem_solving","intent":"establish_ownership","depth":2,'
        '"probe_shape":"failure_mode"}'
    )
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2", "q3"],
        candidate_turns=["a1", "a2", "a3"],
        initial_phase_index=2,
        initial_probe_count=2,
    )
    await flow.generate_next_question(
        "I owned retries and timeouts on the billing API."
    )
    assert flow.phase_index == 3


def test_candidate_map_moves_to_technical_baseline_after_one_turn() -> None:
    from products.interviewer.policy import PolicyState, decide_next_action

    decision = decide_next_action(
        PolicyState(
            candidate_turn_count=1,
            interviewer_turn_count=2,
            phase_name="candidate_map",
            has_uncovered_competencies=True,
            competency_id=None,
        )
    )

    assert decision.action == "ASK_BASELINE"
    assert decision.forced_flow_decision == "advance"


@pytest.mark.asyncio
async def test_policy_mode_opening_cites_resume_or_jd_materials() -> None:
    llm = FakeLlm(
        '{"question":"Welcome! I saw you worked on a machine learning classifier '
        '\u2014 could you introduce yourself and your background?","intent":"opening","depth":1}'
    )
    definition = _definition()
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=definition,
        candidate_profile={
            "claims": [{"claim_id": "c1", "value": "Built a machine learning classifier"}]
        },
        job_description="Looking for an engineer skilled in data structures and algorithms.",
        initial_phase_index=0,
    )

    await flow.generate_next_question(None)

    prompt = llm.messages[0][0]["content"]
    assert "ONE" in prompt.upper() or "one" in prompt.lower()
    assert "machine learning classifier" in prompt
    assert "own words" in prompt.lower() or "vary" in prompt.lower()

@pytest.mark.asyncio
async def test_policy_mode_opening_falls_back_only_on_llm_failure() -> None:
    class FailingLlm:
        async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
            raise RuntimeError("provider unavailable")

    flow = InterviewFlow(
        {"phases": []},
        FailingLlm(),
        interview_definition=_definition(),
        candidate_profile={"claims": [{"claim_id": "c1", "value": "Built a classifier"}]},
        job_description="Data structures and algorithms role.",
        initial_phase_index=0,
    )

    from products.interviewer.flow import FALLBACK_OPENING

    question = await flow.generate_next_question(None)

    assert question != FALLBACK_OPENING
    assert "this role" in question.lower() or "introduce yourself" in question.lower()


def test_ownership_prompt_uses_ownership_phrasing_not_method() -> None:
    from products.interviewer.policy import PolicyDecision

    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )
    policy = PolicyDecision(
        action="PROBE_FOR_OWNERSHIP",
        forced_flow_decision="probe",
        allow_llm_decision=False,
        current_depth=2,
        max_depth=3,
        competency_id="problem_solving",
        intent="establish_ownership",
        reason="required assessment intent still missing",
        section="competency_assessment",
    )
    prompt, _ = flow._structured_system_prompt(
        "I solved a graph problem.",
        policy,
    )
    assert "personally did versus the team" in prompt
    assert "steps or mechanism they used" not in prompt
    assert "graph" in prompt.lower()
    assert "required probe_shape" in prompt.lower()


def test_phrasing_prompt_omits_answer_evaluation() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )
    flow.last_answer_evaluation = {
        "technical_substance": "partial",
        "key_facts_stated": ["used graph search"],
        "factually_correct": True,
    }
    prompt, _ = flow._structured_system_prompt(
        "I solved a graph problem.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )
    assert "answer_evaluation" not in prompt
    assert "Previous-turn evaluation" in prompt
    assert "used graph search" in prompt


def test_keyword_rich_answer_keeps_missing_intents() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro"],
        initial_phase_index=2,
    )
    flow.last_question_intent = "establish_context"
    flow._record_answer_quality(
        "I used it because the team project was interesting.",
        is_intro_reply=False,
    )
    assert flow.coverage["problem_solving"]["covered_intents"] == []
    assert "establish_context" in flow.coverage["problem_solving"]["missing_intents"]


def test_probe_shape_rotates_away_from_last_shape() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        initial_phase_index=2,
    )
    flow.last_probe_shape["problem_solving"] = "why"
    assert flow._next_probe_shape("problem_solving", "establish_ownership") == "failure_mode"
    flow.last_probe_shape["problem_solving"] = "trade_off"
    assert flow._next_probe_shape("problem_solving", "establish_ownership") == "why"
    assert flow._next_probe_shape("problem_solving", "opening") == ""


class EmptyThenQuestionLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict]] = []

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        self.messages.append(messages)
        self.calls += 1
        if self.calls == 1:
            return
            yield
        yield (
            '{"question":"What graph problem did you solve?",'
            '"competency_id":"problem_solving","intent":"establish_context","depth":1,'
            '"probe_shape":"why"}'
        )

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        self.messages.append(messages)
        return (
            '{"question":"What graph problem did you solve?",'
            '"competency_id":"problem_solving","intent":"establish_context","depth":1,'
            '"probe_shape":"why"}'
        )


@pytest.mark.asyncio
async def test_empty_stream_retries_once_then_speaks() -> None:
    llm = EmptyThenQuestionLlm()
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )

    chunks = [
        chunk
        async for chunk in flow.generate_next_question_stream("I solved a graph problem.")
    ]

    assert llm.calls == 2
    assert "".join(chunks) == "What graph problem did you solve?"


class GatedStreamLlm:
    def __init__(self) -> None:
        self.release_rest = asyncio.Event()
        self.rest_requested = False

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        yield '{"question": "What graph problem'
        await self.release_rest.wait()
        self.rest_requested = True
        yield ' did you solve, and what was the situation?"}'


@pytest.mark.asyncio
async def test_policy_stream_yields_question_before_json_closes() -> None:
    llm = GatedStreamLlm()
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )
    agen = flow.generate_next_question_stream("I solved a graph problem.")
    chunk = await asyncio.wait_for(agen.__anext__(), timeout=1)
    assert "graph problem" in chunk
    assert llm.rest_requested is False
    llm.release_rest.set()
    rest = [piece async for piece in agen]
    assert "situation" in "".join([chunk, *rest])


class EmptyThenInvalidLlm:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        self.stream_calls += 1
        return
        yield

    async def generate_reply(self, messages: list[dict], **_kwargs) -> str:
        return "not-json"


@pytest.mark.asyncio
async def test_empty_stream_keeps_hooked_fallback_when_nothing_spoken() -> None:
    llm = EmptyThenInvalidLlm()
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )
    chunks = [
        chunk
        async for chunk in flow.generate_next_question_stream("I solved a graph problem.")
    ]
    spoken = "".join(chunks)
    assert llm.stream_calls == 2
    assert "Which algorithm did you use" in spoken
    assert "You mentioned" not in spoken
    assert not spoken.lower().startswith("regarding ")
    assert "and why" not in spoken.lower()


def test_fallback_spoken_question_uses_ladder_without_candidate_hook() -> None:
    from products.interviewer.policy import PolicyDecision

    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["q1", "q2"],
        candidate_turns=["intro", "background"],
        initial_phase_index=2,
    )
    policy = PolicyDecision(
        action="PROBE_FOR_OWNERSHIP",
        forced_flow_decision="probe",
        allow_llm_decision=False,
        current_depth=2,
        max_depth=3,
        competency_id="problem_solving",
        intent="establish_ownership",
        reason="required assessment intent still missing",
        section="competency_assessment",
    )
    spoken = flow._fallback_spoken_question(
        policy,
        last_turn="I migrated Redis after the outage.",
    )
    assert "You mentioned" not in spoken
    assert not spoken.lower().startswith("regarding ")
    assert "personally" in spoken.lower()


def test_legacy_flag_off_uses_structured_prompt() -> None:
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        FakeLlm(),
        allow_legacy_flow=False,
        candidate_turns=["I already introduced myself."],
    )
    prompt, _ = flow._prompt_for_turn("I led the rollout.")
    assert "POLICY ENGINE" in prompt
    assert "DECISION:" not in prompt


def test_legacy_flag_on_uses_decision_prompt() -> None:
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        FakeLlm(),
        allow_legacy_flow=True,
        candidate_turns=["I already introduced myself."],
    )
    prompt, _ = flow._prompt_for_turn("I led the rollout.")
    assert "RESUME BRIEF" in prompt
    assert "POLICY ENGINE" not in prompt

