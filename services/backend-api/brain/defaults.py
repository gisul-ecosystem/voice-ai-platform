"""Safe default policies for the interview brain."""
from __future__ import annotations

from models.brain import (
    CompetencyLadder,
    DurationMinutes,
    EndingPolicy,
    NonAnswerPolicy,
    QuestionLadderStep,
    ScoringPolicy,
    TimePolicy,
    VoicePolicy,
)

DEFAULT_PROMPT_VERSION = "interviewer-system-v2"

DEFAULT_ALLOWED_PROBES = [
    "What was your specific responsibility?",
    "What action did you personally take?",
    "How did you decide on that approach?",
    "What was the outcome?",
    "What would you change if you did it again?",
]

DEFAULT_TIME_POLICY = TimePolicy(
    duration_minutes=30,
    soft_end_minutes=27,
    target_end_minutes=30,
    hard_end_minutes=35,
    allow_final_addition=True,
)

DEFAULT_NON_ANSWER_POLICY = NonAnswerPolicy(
    clarify_after=1,
    rephrase_after=2,
    change_topic_after=3,
    confirm_continue_after=4,
    count_stt_failures=False,
    count_network_failures=False,
    count_clarification_requests=False,
)

DEFAULT_ENDING_POLICY = EndingPolicy(
    offer_final_addition=True,
    announce_scores=False,
    announce_hiring_decision=False,
    closing_message_style="standard",
)

DEFAULT_VOICE_POLICY = VoicePolicy(
    provider="deepgram",
    voice_id="aura-asteria-en",
    model_id="aura-asteria-en",
    fallback_policy="same_voice_retry_then_pause",
    preflight_required=True,
)

DEFAULT_SCORING_POLICY = ScoringPolicy(
    enabled=True,
    human_review_required=True,
    allow_not_assessed=True,
    recommendation_visible_to_recruiter=True,
    recommendation_visible_to_candidate=False,
    override_requires_reason=True,
    min_evidence_per_competency=1,
)


def default_time_policy_for_duration(duration: DurationMinutes) -> TimePolicy:
    """Scale soft/hard boundaries for 15/30/45 minute interviews."""
    soft = max(duration - 3, 10 if duration >= 15 else duration)
    hard = duration + 5
    return TimePolicy(
        duration_minutes=duration,
        soft_end_minutes=soft,
        target_end_minutes=duration,
        hard_end_minutes=hard,
        allow_final_addition=True,
    )


def default_question_ladder(
    competency_id: str,
    competency_name: str | None = None,
) -> CompetencyLadder:
    """Technical depth ladder used when no custom ladder is supplied.

    Objectives set the evidence bar for each rung. The example questions are
    prompt guidance and emergency fallbacks only -- the interviewer writes its
    own wording from the candidate's actual answer.
    """
    topic = (competency_name or competency_id or "this competency").strip()
    return CompetencyLadder(
        competency_id=competency_id,
        levels=[
            QuestionLadderStep(
                depth=1,
                intent="establish_context",
                objective=(
                    f"Get one concrete, named piece of {topic} work — the actual "
                    f"problem, system or dataset, not a job description"
                ),
                example_question=f"Which specific {topic} problem did you work on most recently?",
            ),
            QuestionLadderStep(
                depth=2,
                intent="establish_ownership",
                objective=(
                    f"Separate what this candidate personally built or decided in "
                    f"that {topic} work from what the team did"
                ),
                example_question=f"Which part of that {topic} work was your own decision?",
            ),
            QuestionLadderStep(
                depth=3,
                intent="applied_understanding",
                objective=(
                    f"Get the mechanism: the named technique used for {topic} and how "
                    f"it works internally, step by step, not just its label"
                ),
                example_question=f"Walk me through how your {topic} approach actually works, step by step.",
            ),
            QuestionLadderStep(
                depth=4,
                intent="problem_or_complexity",
                objective=(
                    f"Get the cost and the breaking points: complexity, latency or "
                    f"resource cost of the {topic} approach, and where it fails"
                ),
                example_question=f"What does that {topic} approach cost in time and space, and where does it break down?",
            ),
            QuestionLadderStep(
                depth=5,
                intent="tradeoff_or_transfer",
                objective=(
                    f"Get the trade-off against a named alternative for {topic}, and "
                    f"the optimisation they would make next"
                ),
                example_question=f"What would you change to make that {topic} solution faster or cheaper, and what would it cost you?",
            ),
        ],
    )
