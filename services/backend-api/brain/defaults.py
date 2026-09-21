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


def default_question_ladder(
    competency_id: str,
    competency_name: str | None = None,
) -> CompetencyLadder:
    """Technical depth ladder used when no custom ladder is supplied."""
    topic = (competency_name or competency_id or "this competency").strip()
    return CompetencyLadder(
        competency_id=competency_id,
        levels=[
            QuestionLadderStep(
                depth=1,
                intent="establish_context",
                objective=f"Identify a concrete technical example involving {topic}",
                example_question=f"Can you describe a technical problem where you used {topic}?",
            ),
            QuestionLadderStep(
                depth=2,
                intent="establish_ownership",
                objective=f"Clarify the candidate's hands-on ownership of {topic}",
                example_question=f"What part of the {topic} solution did you personally implement?",
            ),
            QuestionLadderStep(
                depth=3,
                intent="applied_understanding",
                objective=f"Assess the implementation approach for {topic}",
                example_question=f"How did you implement the {topic} solution, and why did you choose that approach?",
            ),
            QuestionLadderStep(
                depth=4,
                intent="problem_or_complexity",
                objective=f"Explore a technical difficulty or constraint in {topic}",
                example_question=f"What was the hardest technical part of the {topic} solution, and how did you handle it?",
            ),
            QuestionLadderStep(
                depth=5,
                intent="tradeoff_or_transfer",
                objective=f"Explore trade-offs and alternative designs for {topic}",
                example_question=f"What trade-off did you make in the {topic} solution, and what would you change now?",
            ),
        ],
    )
