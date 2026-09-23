"""Question validator and structured generation parsing."""
from __future__ import annotations

import pytest

from products.interviewer.prompts import ACTION_PHRASING
from products.interviewer.validator import (
    AnswerEvaluation,
    GeneratedQuestion,
    ladder_fallback_question,
    parse_generated_question,
    validate_generated_question,
)


def test_near_duplicate_questions_are_rejected() -> None:
    generated = GeneratedQuestion(
        question="Can you describe the project you worked on?",
        competency_id="project",
        intent="establish_context",
        depth=1,
    )
    result = validate_generated_question(
        generated,
        definition=None,
        policy_competency_id="project",
        policy_intent="establish_context",
        policy_depth=1,
        max_depth=3,
        recent_questions=["Could you tell me about the project you worked on?"],
        allowed_probes=[],
    )

    assert result.ok is False
    assert "duplicate_question" in result.reasons


def test_adjacent_same_frame_reask_is_rejected() -> None:
    """Turn-4/5 style: same frame, different nouns — must not pass validator."""
    generated = GeneratedQuestion(
        question=(
            "Can you describe the specific steps you followed to implement "
            "exponential backoff with idempotency keys in Redis?"
        ),
        competency_id="ownership",
        intent="applied_understanding",
        depth=3,
    )
    result = validate_generated_question(
        generated,
        definition=None,
        policy_competency_id="ownership",
        policy_intent="applied_understanding",
        policy_depth=3,
        max_depth=4,
        recent_questions=[
            "Can you describe the specific actions you took to design the "
            "routing and retries for the payments FastAPI service?"
        ],
        allowed_probes=[],
    )
    assert result.ok is False
    assert "repeated_question_frame" in result.reasons


def test_hook_prefers_tech_entity_over_trailing_filler() -> None:
    from products.interviewer.validator import extract_hook_fact

    hook = extract_hook_fact(
        "The main failure mode was webhook storms. We rate-limited and "
        "added a dead-letter queue so operators could replay safely."
    )
    assert hook.lower() in {
        "webhook storms",
        "dead-letter queue",
        "dead letter queue",
    }
    assert hook.lower() not in {"safely", "overall", "fine"}


def test_hook_rejects_mid_phrase_fragments_from_sales_answers() -> None:
    """Sales dry-run regression: never hook on 'One deal was' / 'the commercial'."""
    from products.interviewer.validator import extract_hook_fact

    deal = extract_hook_fact(
        "One deal was a manufacturing customer with procurement and legal "
        "blocking on liability caps."
    )
    assert deal.lower() not in {"one deal was", "deal was", "one deal", "the deal"}
    assert "was" not in deal.lower().split()
    assert deal.lower() in {
        "manufacturing customer",
        "procurement",
        "liability caps",
        "liability",
        "manufacturing",
    } or (
        len(deal.split()) >= 2
        and deal.lower().split()[0] not in {"one", "the", "a", "an"}
    )

    commercial = extract_hook_fact(
        "I owned the commercial negotiation and stakeholder map; my SE owned "
        "the demo. I ran the procurement calls."
    )
    assert commercial.lower() not in {"the commercial", "owned the commercial"}
    assert commercial.lower().split()[0] not in {"the", "a", "an", "owned"}
    assert "commercial" in commercial.lower()
    assert commercial.lower() in {
        "commercial negotiation",
        "stakeholder map",
        "procurement calls",
        "commercial",
        "negotiation",
        "procurement",
    } or (
        "commercial" in commercial.lower()
        and commercial.lower().split()[0] not in {"the", "a", "an", "owned"}
    )


def test_compound_detector_flags_sparse_and_if_single_question_mark() -> None:
    """Sparse dry-run regression: one '?' but two asks joined by 'and if'."""
    from products.interviewer.validator import looks_like_compound_question

    sparse = (
        "Can you share how you determined the appropriate indexes to use "
        "and if you encountered any performance issues that required adjustments?"
    )
    assert sparse.count("?") == 1
    assert looks_like_compound_question(sparse) is True

    # conjunction + wh (sales-style), still one '?'
    assert looks_like_compound_question(
        "What led you to choose a shorter pilot in exchange for a lower "
        "liability cap, and how did you evaluate the potential impact?"
    )

    # Two '?' still compound
    assert looks_like_compound_question(
        "How did you pick indexes? Did you also hit performance issues?"
    )

    # Benign: list join / conditional without a second ask shape
    assert looks_like_compound_question(
        "What would you change if you did it again?"
    ) is False
    assert looks_like_compound_question(
        "Can you describe the approach and the outcome?"
    ) is False
    assert looks_like_compound_question(
        "How did you handle pricing and legal constraints on that deal?"
    ) is False


def test_clean_hook_gate_rejects_sales_fragments() -> None:
    from products.interviewer.validator import (
        GeneratedQuestion,
        extract_hook_fact,
        hook_stem_tokens,
        is_clean_hook_fact,
        validate_generated_question,
    )

    assert is_clean_hook_fact("One deal was") is False
    assert is_clean_hook_fact("the commercial") is False
    assert is_clean_hook_fact("commercial negotiation") is True
    assert is_clean_hook_fact("manufacturing customer") is True
    assert is_clean_hook_fact("kafka") is True
    assert is_clean_hook_fact("Kafka") is True  # tech token match is case-insensitive via content filter + set

    # Extractor + stem alignment: multi-word hook yields content stems.
    hook = extract_hook_fact(
        "I owned the commercial negotiation and stakeholder map."
    )
    assert is_clean_hook_fact(hook)
    stems = hook_stem_tokens(hook)
    assert "commercial" in stems or "negotiation" in stems
    assert "the" not in stems
    assert "owned" not in stems

    # Validator rejects unclean hook_fact even if stem text appears in question.
    bad = GeneratedQuestion(
        question="You mentioned One deal was. Tell me about that negotiation.",
        competency_id="negotiation",
        intent="establish_context",
        depth=1,
    )
    result = validate_generated_question(
        bad,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_context",
        policy_depth=1,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
        hook_fact="One deal was",
    )
    assert result.ok is False
    assert "invalid_hook_phrase" in result.reasons


def test_seal_marks_asked_intents_assessed_insufficient() -> None:
    from products.interviewer.coverage import (
        init_coverage,
        mark_intent_asked,
        mark_missing_intents_insufficient,
    )

    coverage = init_coverage(
        {
            "competencies": [
                {
                    "id": "negotiation",
                    "min_assessment_intents": [
                        "establish_context",
                        "establish_ownership",
                        "applied_understanding",
                    ],
                }
            ]
        }
    )
    mark_intent_asked(coverage, competency_id="negotiation", intent="applied_understanding")
    # Simulate covered context/ownership so only applied remains missing.
    coverage["negotiation"]["covered_intents"] = [
        "establish_context",
        "establish_ownership",
    ]
    coverage["negotiation"]["missing_intents"] = ["applied_understanding"]
    coverage["negotiation"]["intent_status"]["establish_context"] = "covered"
    coverage["negotiation"]["intent_status"]["establish_ownership"] = "covered"
    mark_missing_intents_insufficient(coverage, competency_id="negotiation")
    assert (
        coverage["negotiation"]["intent_status"]["applied_understanding"]
        == "assessed_insufficient"
    )


def test_gap_check_ladder_default_must_not_be_compound() -> None:
    """Sales turn-6 regression: gap_check safe_gated used a dual-ask default."""
    from products.interviewer.validator import (
        ladder_fallback_question,
        looks_like_compound_question,
    )

    question = ladder_fallback_question(
        None, competency_id=None, intent="gap_check"
    )
    assert looks_like_compound_question(question) is False
    assert "and what" not in question.lower()


@pytest.mark.asyncio
async def test_safe_gated_path_revalidates_and_ships_clean_not_greenwashed() -> None:
    """ok:True must mean the spoken text actually passed validation.

    Force LLM output that fails validation so the coerce path hits safe_gated;
    the sales turn-6 shape (Regarding X, … and what happened…) must not ship
    under a quietly green ok:True.
    """
    from products.interviewer.flow import InterviewFlow
    from products.interviewer.validator import looks_like_compound_question
    from tests.test_interview_quality import FakeLlm

    # First reply: compound (fails). Rewrite reply: also compound (fails again).
    bad = (
        '{"question": "Regarding Procurement signed, could you share one '
        'specific example of work you personally handled, and what happened '
        'as a result?", "competency_id": "negotiation", '
        '"intent": "gap_check", "depth": 1}'
    )
    llm = FakeLlm(bad, bad)
    flow = InterviewFlow(
        {"phases": []},
        llm,
        interview_definition=_sales_definition(),
        interviewer_turns=[
            "Thanks for joining.",
            "Tell me about a complex deal you negotiated.",
        ],
        resume_text="Taylor closed manufacturing deals with procurement.",
        job_description="Enterprise Account Executive negotiation.",
        candidate_turns=[
            "I'm Taylor.",
            "One deal was a manufacturing customer.",
        ],
    )
    # Seed policy-ish state: last ask was applied so gap/probe path is live.
    flow.last_question_competency_id = "negotiation"
    flow.last_question_intent = "applied_understanding"
    flow.coverage = {
        "negotiation": {
            "status": "partial",
            "required_intents": [
                "establish_context",
                "establish_ownership",
                "applied_understanding",
            ],
            "covered_intents": ["establish_context", "establish_ownership"],
            "missing_intents": ["applied_understanding"],
            "evidence_ids": [],
            "intent_status": {
                "establish_context": "covered",
                "establish_ownership": "covered",
                "applied_understanding": "asked",
            },
        }
    }
    # Jump outline onto negotiation competency phase.
    from products.interviewer.policy import outline_from_definition

    outline = outline_from_definition(_sales_definition())
    flow.phases = list((outline or {}).get("phases") or [])
    for index, phase in enumerate(flow.phases):
        if phase.get("competency_id") == "negotiation":
            flow.phase_index = index
            break

    question = await flow.generate_next_question(
        "Yeah, that trade closed the deal. Procurement signed after we "
        "agreed on the pilot length."
    )
    assert looks_like_compound_question(question) is False
    # Must not greenwash: either truly ok, or honest False — never ok True
    # while reasons only claim safe_gated without a real pass.
    if flow.last_validator_ok is True:
        assert "unvalidated" not in (flow.last_validator_reasons or [])
        # A green ok must not be sitting on a compound ask.
        assert looks_like_compound_question(question) is False
    else:
        assert flow.last_validator_ok is False
def _sales_definition() -> dict:
    return {
        "prompt_version": "interviewer-system-v2",
        "allowed_probes": [
            "What was your specific responsibility?",
            "What action did you personally take?",
            "How did you decide on that approach?",
            "What was the outcome?",
            "What would you change if you did it again?",
        ],
        "competencies": [
            {
                "id": "negotiation",
                "name": "Negotiation",
                "definition": "Reaches agreements that serve the customer and the company",
                "max_depth": 3,
                "min_assessment_intents": [
                    "establish_context",
                    "establish_ownership",
                    "applied_understanding",
                ],
                "evidence_expected": ["context of the work", "personal contribution"],
            }
        ],
        "question_ladders": [
            {
                "competency_id": "negotiation",
                "levels": [
                    {
                        "depth": 1,
                        "intent": "establish_context",
                        "objective": "Understand the deal situation",
                        "example_question": "Can you briefly describe the situation?",
                    }
                ],
            }
        ],
    }


def test_parse_generated_question_from_json() -> None:
    parsed = parse_generated_question(
        '{"question": "What part of that deal did you personally handle?", '
        '"competency_id": "negotiation", "intent": "establish_ownership", '
        '"depth": 2, "source_claim_ids": ["claim_project_1"]}'
    )
    assert parsed is not None
    assert parsed.competency_id == "negotiation"
    assert parsed.intent == "establish_ownership"
    assert parsed.source_claim_ids == ["claim_project_1"]


def test_validator_rejects_ungrounded_technical_jargon_for_sales() -> None:
    generated = GeneratedQuestion(
        question="What API or queue did you use in that negotiation?",
        competency_id="negotiation",
        intent="establish_ownership",
        depth=2,
    )
    result = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
        job_description="Enterprise sales executive owning pipeline and negotiation.",
        resume_text="Campus ambassador for a retail brand.",
        recent_turns=["I interned in campus sales."],
    )
    assert result.ok is False
    assert "ungrounded_term" in result.reasons


def test_validator_rejects_protected_topics_and_duplicates() -> None:
    generated = GeneratedQuestion(
        question="How old are you and where were you born?",
        competency_id="negotiation",
        intent="establish_context",
        depth=1,
    )
    result = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_context",
        policy_depth=1,
        max_depth=3,
        recent_questions=["How old are you and where were you born?"],
        allowed_probes=_sales_definition()["allowed_probes"],
    )
    assert "protected_topic" in result.reasons
    assert "duplicate_question" in result.reasons


def test_ladder_fallback_is_domain_neutral() -> None:
    spoken = ladder_fallback_question(
        _sales_definition(),
        competency_id="negotiation",
        intent="establish_context",
    )
    assert "API" not in spoken
    assert "queue" not in spoken.lower()
    assert "situation" in spoken.lower()


def test_validator_preserves_evaluation_and_tags_on_success() -> None:
    evaluation = AnswerEvaluation(
        technical_substance="deep",
        key_facts_stated=["closed a $2M renewal"],
        reasoning="Candidate described the specific renewal mechanics.",
        matches_evidence_expected=True,
    )
    generated = GeneratedQuestion(
        question="What would have happened if the customer pushed back on price?",
        competency_id="negotiation",
        intent="establish_ownership",
        depth=2,
        answer_evaluation=evaluation,
        depth_tag="applied",
        probe_shape="trade_off",
    )
    result = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
    )
    assert result.ok is True
    assert result.question.answer_evaluation is evaluation
    assert result.question.depth_tag == "applied"
    assert result.question.probe_shape == "trade_off"


def test_probe_action_phrasing_is_unique() -> None:
    keys = [
        "PROBE_FOR_CONTEXT",
        "PROBE_FOR_OWNERSHIP",
        "PROBE_FOR_METHOD",
        "PROBE_FOR_REASONING",
        "PROBE_FOR_RESULT",
        "PROBE_FOR_REFLECTION",
    ]
    notes = [ACTION_PHRASING[key] for key in keys]
    assert len(set(notes)) == len(notes)


def test_validator_requires_hook_stem_on_live_probes() -> None:
    generated = GeneratedQuestion(
        question="What would you change about the approach next time?",
        competency_id="negotiation",
        intent="establish_ownership",
        depth=2,
    )
    missing = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
        recent_turns=["We used Redis during that renewal."],
        hook_fact="Redis",
    )
    assert missing.ok is False
    assert "missing_hook_stem" in missing.reasons

    hooked = validate_generated_question(
        GeneratedQuestion(
            question="What broke when Redis failed?",
            competency_id="negotiation",
            intent="establish_ownership",
            depth=2,
        ),
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
        recent_turns=["We used Redis during that renewal."],
        hook_fact="Redis",
    )
    assert hooked.ok is True


def test_validator_rejects_repeated_six_word_prefix() -> None:
    generated = GeneratedQuestion(
        question="What part of that deal did you change afterward?",
        competency_id="negotiation",
        intent="establish_ownership",
        depth=2,
    )
    result = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=["What part of that deal did you personally handle?"],
        allowed_probes=_sales_definition()["allowed_probes"],
    )
    assert result.ok is False
    assert "repeated_prefix" in result.reasons


def test_validator_rejects_repeated_probe_shape() -> None:
    generated = GeneratedQuestion(
        question="Why did you choose Redis for that deal?",
        competency_id="negotiation",
        intent="establish_ownership",
        depth=2,
        probe_shape="why",
    )
    result = validate_generated_question(
        generated,
        definition=_sales_definition(),
        policy_competency_id="negotiation",
        policy_intent="establish_ownership",
        policy_depth=2,
        max_depth=3,
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
        recent_turns=["We used Redis during that renewal."],
        hook_fact="Redis",
        required_probe_shape="failure_mode",
        last_probe_shape="why",
    )
    assert result.ok is False
    assert "repeated_probe_shape" in result.reasons
