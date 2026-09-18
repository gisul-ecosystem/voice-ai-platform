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
    provider="elevenlabs",
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


def default_question_ladder(competency_id: str) -> CompetencyLadder:
    """Domain-neutral depth ladder used when no custom ladder is supplied."""
    return CompetencyLadder(
        competency_id=competency_id,
        levels=[
            QuestionLadderStep(
                depth=1,
                intent="establish_context",
                objective="Understand the situation or work the candidate is describing",
                example_question="Can you briefly describe the situation?",
            ),
            QuestionLadderStep(
                depth=2,
                intent="establish_ownership",
                objective="Clarify what the candidate personally did",
                example_question="What part of that did you personally handle?",
            ),
            QuestionLadderStep(
                depth=3,
                intent="applied_understanding",
                objective="Understand how the candidate carried out the work",
                example_question="How did you approach that work?",
            ),
            QuestionLadderStep(
                depth=4,
                intent="problem_or_complexity",
                objective="Explore a difficulty, constraint, or failure",
                example_question="What was difficult about that, and how did you handle it?",
            ),
            QuestionLadderStep(
                depth=5,
                intent="tradeoff_or_transfer",
                objective="Explore judgment, alternatives, or what they would change",
                example_question="Looking back, what would you change and why?",
            ),
        ],
    )
