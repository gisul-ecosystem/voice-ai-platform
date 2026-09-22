"""Question validator and structured generation parsing."""
from __future__ import annotations

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


def test_validator_rejects_trivia_questions() -> None:
    generated = GeneratedQuestion(
        question="Here is a brain teaser: how many ping-pong balls fit in a bus?",
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
        recent_questions=[],
        allowed_probes=_sales_definition()["allowed_probes"],
    )

    assert result.ok is False
    assert "trivia_question" in result.reasons


def test_ladder_fallback_is_domain_neutral() -> None:
    spoken = ladder_fallback_question(
        _sales_definition(),
        competency_id="negotiation",
        intent="establish_context",
    )
    assert "API" not in spoken
    assert "queue" not in spoken.lower()
    assert "situation" in spoken.lower()


def test_ladder_fallback_anchors_to_candidate_answer() -> None:
    spoken = ladder_fallback_question(
        _sales_definition(),
        competency_id="negotiation",
        intent="baseline",
        last_candidate_turn="I optimized arrays and strings.",
    )
    assert "optimized arrays and strings" in spoken
    assert "personally" in spoken.lower()


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


def test_validator_allows_natural_question_without_hook_stem() -> None:
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
    assert missing.ok is True

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


def test_validator_still_rejects_near_duplicate_question() -> None:
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
    assert "duplicate_question" in result.reasons


def test_validator_allows_repeated_probe_shape_when_question_is_valid() -> None:
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
    assert result.ok is True
