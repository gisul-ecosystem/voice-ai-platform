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
    """Depth ladder of what to find out. No sample questions — the interviewer writes those."""
    topic = (competency_name or competency_id or "this competency").strip()
    return CompetencyLadder(
        competency_id=competency_id,
        levels=[
            QuestionLadderStep(
                depth=1,
                intent="establish_context",
                objective=f"A specific situation where they used {topic} in this kind of job",
            ),
            QuestionLadderStep(
                depth=2,
                intent="establish_ownership",
                objective=f"What they personally did on {topic}, apart from other people",
            ),
            QuestionLadderStep(
                depth=3,
                intent="applied_understanding",
                objective=f"How they carried out {topic} and why they chose that approach",
            ),
            QuestionLadderStep(
                depth=4,
                intent="problem_or_complexity",
                objective=f"What was difficult about {topic} and how they handled it",
            ),
            QuestionLadderStep(
                depth=5,
                intent="tradeoff_or_transfer",
                objective=f"The trade-off they made on {topic} and what they would do differently",
            ),
        ],
    )
