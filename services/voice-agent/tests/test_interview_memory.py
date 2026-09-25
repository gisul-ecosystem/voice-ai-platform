"""Dossier and interview thread stay available after the resume prefix and competency change."""
from __future__ import annotations

import pytest

from products.interviewer.flow import InterviewFlow, format_dossier
from products.interviewer.policy import PolicyDecision
from tests.test_interview_policy_flow import FakeLlm, _definition


def test_dossier_keeps_a_fact_from_the_second_half_of_the_resume() -> None:
    filler = "Early campus activity and coursework. " * 40
    later = "Closed the north region quota after a price objection."
    resume = filler + "\n" + later
    brief = format_dossier({}, resume)
    assert later in brief
    assert len(resume) > 700

    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        resume_text=resume,
        job_description="Enterprise sales executive.",
    )
    prompt, _ = flow._structured_system_prompt(None, None)
    assert later in prompt


def test_earlier_answer_survives_a_competency_change() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["What part of that renewal did you handle?"],
        candidate_turns=["I closed a retail renewal after the buyer objected on price."],
        resume_text="Campus sales internship.",
        job_description="Enterprise sales executive.",
    )
    flow._absorb_memory(
        note="They closed a retail renewal after a price objection.",
        answer="I closed a retail renewal after the buyer objected on price.",
        question="How did you decide the discount?",
    )
    policy = PolicyDecision(
        action="PROBE_FOR_CONTEXT",
        forced_flow_decision="probe",
        allow_llm_decision=False,
        current_depth=1,
        max_depth=3,
        competency_id="communication",
        intent="establish_context",
        reason="next competency",
        section="competency_assessment",
    )
    prompt, _ = flow._structured_system_prompt(
        "I walked the buyer through the proposal.",
        policy,
    )
    assert "retail renewal" in prompt
    assert "buyer" in prompt.lower()


def test_sales_craft_is_about_the_role_and_not_a_script() -> None:
    from products.interviewer.prompts import interview_craft

    sales = interview_craft(
        "Enterprise Sales Executive",
        "senior",
        "Own pipeline, negotiation, and quota.",
    )
    engineering = interview_craft("Backend Engineer", "junior", "Build APIs.")
    assert "deal" in sales.lower() or "customer" in sales.lower()
    assert "senior" in sales.lower()
    assert "?" not in sales
    assert "Can you" not in sales
    assert "system" in engineering.lower() or "built" in engineering.lower()
    assert "quota" not in engineering.lower()


def test_partial_answer_presses_with_callback_and_evidence() -> None:
    from products.interviewer.policy import PolicyDecision, PolicyState, _delivery_mode

    decision = PolicyDecision(
        action="PROBE_FOR_OWNERSHIP",
        forced_flow_decision="probe",
        allow_llm_decision=False,
        current_depth=2,
        max_depth=3,
        competency_id="negotiation",
        intent="establish_ownership",
        reason="ownership still missing",
        section="competency_assessment",
        evidence_topic="price objection",
        gap_kind="partial",
    )
    state = PolicyState(
        previous_competency_id="negotiation",
        answer_quality="partial",
        hook_fact="price objection",
    )
    assert _delivery_mode(decision, state) == "press"
    definition = _definition()
    definition["competencies"] = [
        {
            "id": "negotiation",
            "name": "Negotiation",
            "max_depth": 3,
            "max_probes": 2,
            "evidence_expected": ["price objection", "personal contribution"],
        }
    ]
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=definition,
        interviewer_turns=["Tell me about a deal you ran."],
        candidate_turns=["The buyer pushed on price."],
        resume_text="Enterprise sales.",
        job_description="Enterprise sales executive.",
        initial_phase_index=2,
    )
    flow.last_hook_fact = "price objection"
    flow.last_answer_quality = "partial"
    flow.last_question_competency_id = "negotiation"
    prompt, _ = flow._structured_system_prompt(
        "The buyer pushed on price during the renewal.",
        decision,
    )
    assert "They said:" in prompt
    assert "You still need:" in prompt
    assert "price" in prompt.lower()


def test_generic_ask_is_rejected_even_when_it_names_the_topic() -> None:
    from products.interviewer.flow import hiring_question_issues

    issues = hiring_question_issues(
        "Can you tell me more about the price objection?",
        callback="price objection",
        evidence_topic="price objection",
        competency_names=["Negotiation"],
        last_answer="The buyer objected on price.",
    )
    assert "not_a_real_question" in issues
    bot = hiring_question_issues(
        "Which specific part of the price objection did you personally own?",
        callback="price objection",
        evidence_topic="price objection",
        competency_names=["Negotiation"],
        last_answer="The buyer objected on price.",
        move="their_part",
    )
    assert "script_line" in bot
    bare = hiring_question_issues(
        "Can you tell me more?",
        callback="price objection",
        evidence_topic="what they said to the buyer",
        competency_names=["Negotiation"],
        last_answer="The buyer objected on price and I held the renewal.",
    )
    assert "not_a_real_question" in bare or "missing_callback" in bare
    wrong = hiring_question_issues(
        "What changed because of the price objection?",
        callback="price objection",
        evidence_topic="what you personally did",
        competency_names=["Negotiation"],
        last_answer="The buyer objected on price.",
        move="their_part",
    )
    assert "wrong_move" in wrong
    tangent = hiring_question_issues(
        "What did you do about the weekend hiking trip?",
        callback="",
        evidence_topic="price objection",
        competency_names=["Negotiation"],
        last_answer="I went hiking over the weekend.",
        move="cut_back",
        work_in_play="the renewal and the price objection",
    )
    assert "follows_tangent" in tangent
    training = hiring_question_issues(
        "How's the training going?",
        callback="",
        evidence_topic="incident handling",
        competency_names=["Reliability"],
        last_answer="Outside of work I have been training for a half marathon and I bake on Sundays.",
        move="what_changed",
        left_interview=True,
    )
    assert "follows_tangent" in training


def test_craft_uses_this_jobs_evidence_not_a_script() -> None:
    from products.interviewer.prompts import interview_craft

    note = interview_craft(
        "Enterprise Sales Executive",
        "senior",
        "Own quota.",
        competency_name="Negotiation",
        evidence=["price objection"],
    )
    assert "price objection" in note
    assert "?" not in note


@pytest.mark.asyncio
async def test_weak_question_is_rewritten_without_a_stock_line() -> None:
    bad = (
        '{"question":"Can you tell me more?",'
        '"competency_id":"negotiation","intent":"establish_ownership","depth":2}'
    )
    better = (
        '{"question":"When the buyer objected on price, what did you say back?",'
        '"competency_id":"negotiation","intent":"establish_ownership","depth":2,'
        '"memory_note":"The buyer objected on price."}'
    )
    definition = _definition()
    definition["competencies"] = [
        {
            "id": "negotiation",
            "name": "Negotiation",
            "max_depth": 3,
            "max_probes": 2,
            "evidence_expected": ["price objection"],
        }
    ]
    llm = FakeLlm(bad, better)
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=definition,
        interviewer_turns=["Tell me about a renewal you handled."],
        candidate_turns=["I work in sales."],
        resume_text="Enterprise sales.",
        job_description="Enterprise sales executive owning negotiation.",
        initial_phase_index=2,
    )
    question = await flow.generate_next_question(
        "The buyer objected on price and I held the renewal."
    )
    assert "How did you approach that work?" not in question
    assert "you mentioned" not in question.lower()
    assert "price" in question.lower() or "buyer" in question.lower()
    rewrite = llm.messages[-1][-1]["content"]
    assert "They said:" in rewrite
    assert "You still need:" in rewrite
    assert "buyer" in rewrite.lower()


@pytest.mark.asyncio
async def test_generic_followup_is_replaced_with_their_context() -> None:
    generic = (
        '{"question":"Can you tell me more?",'
        '"competency_id":"negotiation","intent":"establish_ownership","depth":2}'
    )
    definition = _definition()
    definition["competencies"] = [
        {
            "id": "negotiation",
            "name": "Negotiation",
            "max_depth": 3,
            "max_probes": 2,
            "evidence_expected": ["price objection"],
        }
    ]
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(generic, generic),
        interview_definition=definition,
        interviewer_turns=["Tell me about a renewal you handled."],
        candidate_turns=["I work in sales."],
        resume_text="Enterprise sales.",
        job_description="Enterprise sales executive owning negotiation.",
        initial_phase_index=2,
    )
    question = await flow.generate_next_question(
        "The buyer objected on price and I held the renewal."
    )
    lowered = question.lower()
    assert "you mentioned" not in lowered
    rewrite = flow.llm_client.messages[-1][-1]["content"]
    assert "They said:" in rewrite
    assert "You still need:" in rewrite
    assert "buyer objected on price" in rewrite.lower()


def test_prompt_keeps_hiring_bar_and_human_followup() -> None:
    flow = InterviewFlow(
        {"phases": []},
        FakeLlm(),
        interview_definition=_definition(),
        interviewer_turns=["Tell me about a deal you ran."],
        resume_text="Enterprise sales.",
        job_description="Enterprise sales executive.",
    )
    prompt, _ = flow._structured_system_prompt(
        "I closed a renewal.",
        flow._current_policy_decision(pending_candidate_turn=True),
    )
    assert "talking to the candidate" in prompt.lower()
    assert "They said:" in prompt
    assert "You still need:" in prompt
    assert "renewal" in prompt.lower()
