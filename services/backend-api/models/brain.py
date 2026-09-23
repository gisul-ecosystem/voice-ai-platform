"""Domain-neutral interview brain contracts (Milestone 0).

These schemas are additive. Existing InterviewSetupConfig / outline flows remain
valid until the runtime migrates behind a feature flag.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SeniorityLevel = Literal["intern", "junior", "mid", "senior", "lead"]
DurationMinutes = Literal[15, 30, 45]
ClaimSource = Literal["resume", "jd", "candidate_statement", "creator"]
ClaimType = Literal[
    "education",
    "employment",
    "internship",
    "project",
    "skill",
    "certification",
    "achievement",
    "responsibility",
    "other",
]
EvidenceStrength = Literal[
    "none",
    "weak",
    "partial",
    "sufficient",
    "strong",
    "contradictory",
]
InterviewSection = Literal[
    "opening",
    "candidate_map",
    "baseline",
    "competency_assessment",
    "scenario",
    "coverage_check",
    "closing",
    "paused",
    "completed",
]
NextAction = Literal[
    "OPEN_INTERVIEW",
    "MAP_CANDIDATE_BACKGROUND",
    "ASK_BASELINE",
    "CLARIFY_CURRENT_ANSWER",
    "PROBE_FOR_CONTEXT",
    "PROBE_FOR_OWNERSHIP",
    "PROBE_FOR_METHOD",
    "PROBE_FOR_REASONING",
    "PROBE_FOR_RESULT",
    "PROBE_FOR_REFLECTION",
    "INCREASE_DEPTH",
    "MOVE_TO_NEXT_COMPETENCY",
    "ASK_APPROVED_SCENARIO",
    "CHECK_REMAINING_GAP",
    "OFFER_FINAL_ADDITION",
    "CLOSE_INTERVIEW",
    "PAUSE_FOR_SERVICE_RECOVERY",
]
QuestionStatus = Literal["planned", "spoken", "interrupted", "answered", "skipped"]
AnswerUsability = Literal[
    "usable",
    "needs_clarification",
    "too_short",
    "off_topic",
    "explicit_unknown",
    "silence",
    "stt_failure",
    "network_failure",
    "candidate_requested_repeat",
]
ProfileType = Literal[
    "final_year_student",
    "recent_graduate",
    "junior",
    "mid",
    "senior",
    "lead",
    "unknown",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ClaimSource
    source_span: str = Field(min_length=1, max_length=4_000)
    page: int | None = Field(default=None, ge=1, le=200)
    confidence: float = Field(ge=0, le=1)
    explicit: bool = True
    confirmed: bool = False


class ExtractedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64)
    text: str = Field(min_length=1, max_length=4_000)
    provenance: SourceReference


class RubricAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5)
    description: str = Field(min_length=4, max_length=500)


class CompetencyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str = Field(min_length=2, max_length=120)
    definition: str = Field(min_length=8, max_length=1_000)
    importance: Literal["high", "medium", "low"] = "high"
    required_level: int = Field(ge=1, le=5, default=3)
    evidence_expected: list[str] = Field(min_length=1, max_length=12)
    min_assessment_intents: list[str] = Field(min_length=1, max_length=12)
    max_depth: int = Field(ge=1, le=5, default=4)
    max_probes: int = Field(ge=0, le=8, default=3)
    rubric: list[RubricAnchor] = Field(min_length=3, max_length=5)
    weight: float | None = Field(default=None, ge=0, le=100)
    # "jd" when derived from the job description, "fallback" when the JD yielded
    # too few competencies and a generic one was substituted.
    source: Literal["jd", "creator", "fallback"] = "jd"

    @field_validator("evidence_expected", "min_assessment_intents")
    @classmethod
    def _trim_nonempty(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty item is required")
        return cleaned

    @model_validator(mode="after")
    def _rubric_covers_scale(self) -> CompetencyDefinition:
        ratings = sorted(anchor.rating for anchor in self.rubric)
        if len(set(ratings)) != len(ratings):
            raise ValueError("rubric ratings must be unique")
        if 1 not in ratings or 5 not in ratings or 3 not in ratings:
            raise ValueError("rubric must include anchors for ratings 1, 3, and 5")
        return self


class QuestionLadderStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth: int = Field(ge=1, le=5)
    intent: str = Field(min_length=2, max_length=64)
    objective: str = Field(min_length=4, max_length=400)
    example_question: str | None = Field(default=None, max_length=500)


class CompetencyLadder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competency_id: str = Field(min_length=2, max_length=64)
    levels: list[QuestionLadderStep] = Field(min_length=1, max_length=5)


class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64)
    competency_id: str = Field(min_length=2, max_length=64)
    level: SeniorityLevel
    scenario: str = Field(min_length=8, max_length=2_000)
    expected_evidence: list[str] = Field(min_length=1, max_length=12)
    source: Literal["creator", "ai_generated", "question_bank"] = "creator"
    approved: bool = False


class TimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_minutes: DurationMinutes = 30
    soft_end_minutes: int = Field(ge=5, le=60, default=27)
    target_end_minutes: int = Field(ge=5, le=60, default=30)
    hard_end_minutes: int = Field(ge=5, le=90, default=35)
    allow_final_addition: bool = True

    @model_validator(mode="after")
    def _ordered_boundaries(self) -> TimePolicy:
        if not (
            self.soft_end_minutes
            <= self.target_end_minutes
            <= self.hard_end_minutes
        ):
            raise ValueError(
                "time boundaries must satisfy soft_end <= target_end <= hard_end"
            )
        if self.target_end_minutes != self.duration_minutes:
            # Target end should match the scheduled duration; soft/hard can differ.
            raise ValueError("target_end_minutes must equal duration_minutes")
        return self


class NonAnswerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarify_after: int = Field(ge=1, le=5, default=1)
    rephrase_after: int = Field(ge=1, le=5, default=2)
    change_topic_after: int = Field(ge=1, le=5, default=3)
    confirm_continue_after: int = Field(ge=1, le=8, default=4)
    count_stt_failures: bool = False
    count_network_failures: bool = False
    count_clarification_requests: bool = False

    @model_validator(mode="after")
    def _ordered_thresholds(self) -> NonAnswerPolicy:
        if not (
            self.clarify_after
            <= self.rephrase_after
            <= self.change_topic_after
            <= self.confirm_continue_after
        ):
            raise ValueError("non-answer thresholds must be non-decreasing")
        return self


class EndingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_final_addition: bool = True
    announce_scores: bool = False
    announce_hiring_decision: bool = False
    closing_message_style: Literal["standard", "brief"] = "standard"


class VoicePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="elevenlabs", min_length=2, max_length=64)
    voice_id: str = Field(default="", max_length=128)
    model_id: str = Field(default="", max_length=128)
    stability: float | None = Field(default=None, ge=0, le=1)
    speed: float | None = Field(default=None, ge=0.5, le=1.5)
    fallback_policy: Literal[
        "same_voice_retry_then_pause",
        "same_voice_retry_then_end",
        "allow_provider_fallback",
    ] = "same_voice_retry_then_pause"
    preflight_required: bool = True


class ScoringPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    human_review_required: bool = True
    allow_not_assessed: bool = True
    recommendation_visible_to_recruiter: bool = True
    recommendation_visible_to_candidate: bool = False
    override_requires_reason: bool = True
    min_evidence_per_competency: int = Field(ge=0, le=20, default=1)


class JobRoleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    occupation_code: str | None = Field(default=None, max_length=64)
    domain: str | None = Field(default=None, max_length=120)
    target_level: SeniorityLevel
    department: str | None = Field(default=None, max_length=120)


class JobIntelligence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: JobRoleSummary
    responsibilities: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    mandatory_requirements: list[ExtractedItem] = Field(
        default_factory=list, max_length=40
    )
    preferred_requirements: list[ExtractedItem] = Field(
        default_factory=list, max_length=40
    )
    knowledge: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    skills: list[ExtractedItem] = Field(default_factory=list, max_length=80)
    tools: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    work_scenarios: list[ExtractedItem] = Field(default_factory=list, max_length=20)
    expected_outcomes: list[ExtractedItem] = Field(default_factory=list, max_length=20)
    raw_job_description: str = Field(min_length=1, max_length=100_000)
    extraction_version: str = Field(default="jd-extractor-v1", max_length=64)
    approved: bool = False
    approved_at: datetime | None = None


class ExperienceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professional_months: int = Field(ge=0, le=600, default=0)
    internship_months: int = Field(ge=0, le=120, default=0)
    profile_type: ProfileType = "unknown"


class CandidateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=2, max_length=64)
    type: ClaimType
    value: str = Field(min_length=1, max_length=2_000)
    provenance: SourceReference
    technologies: list[str] = Field(default_factory=list, max_length=40)
    candidate_role: str | None = Field(default=None, max_length=200)


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    education: list[ExtractedItem] = Field(default_factory=list, max_length=20)
    professional_experience: list[ExtractedItem] = Field(
        default_factory=list, max_length=40
    )
    internships: list[ExtractedItem] = Field(default_factory=list, max_length=20)
    projects: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    skills_claimed: list[ExtractedItem] = Field(default_factory=list, max_length=80)
    certifications: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    achievements: list[ExtractedItem] = Field(default_factory=list, max_length=40)
    languages: list[ExtractedItem] = Field(default_factory=list, max_length=20)
    experience_summary: ExperienceSummary = Field(default_factory=ExperienceSummary)
    claims: list[CandidateClaim] = Field(default_factory=list, max_length=200)
    raw_resume_text: str | None = Field(default=None, max_length=100_000)
    extraction_version: str = Field(default="resume-extractor-v1", max_length=64)
    confirmed: bool = False
    confirmed_at: datetime | None = None


class InterviewDefinitionDraft(BaseModel):
    """Mutable creator draft before publish."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    language: str = Field(min_length=2, max_length=32, default="English")
    timezone: str = Field(min_length=1, max_length=64, default="UTC")
    job_intelligence: JobIntelligence
    competencies: list[CompetencyDefinition] = Field(min_length=1, max_length=8)
    question_ladders: list[CompetencyLadder] = Field(default_factory=list, max_length=8)
    allowed_probes: list[str] = Field(default_factory=list, max_length=40)
    scenario_bank: list[ScenarioDefinition] = Field(default_factory=list, max_length=20)
    time_policy: TimePolicy = Field(default_factory=TimePolicy)
    non_answer_policy: NonAnswerPolicy = Field(default_factory=NonAnswerPolicy)
    ending_policy: EndingPolicy = Field(default_factory=EndingPolicy)
    voice_policy: VoicePolicy = Field(default_factory=VoicePolicy)
    scoring_policy: ScoringPolicy = Field(default_factory=ScoringPolicy)
    prompt_version: str = Field(default="interviewer-system-v2", max_length=64)
    resume_required: bool = False


class InterviewDefinitionVersion(InterviewDefinitionDraft):
    """Immutable published definition used by live interviews."""

    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(min_length=8, max_length=64)
    template_id: str = Field(min_length=8, max_length=64)
    version: int = Field(ge=1)
    published_at: datetime
    published_by: str = Field(min_length=1, max_length=128)
    status: Literal["published"] = "published"


class InterviewQuestionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    competency_id: str | None = Field(default=None, max_length=64)
    intent: str = Field(min_length=2, max_length=64)
    depth: int = Field(ge=1, le=5, default=1)
    text: str = Field(min_length=1, max_length=2_000)
    source_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    status: QuestionStatus = "planned"
    asked_at: datetime | None = None
    prompt_version: str | None = Field(default=None, max_length=64)
    definition_id: str | None = Field(default=None, max_length=64)
    policy_action: str | None = Field(default=None, max_length=64)
    validator_ok: bool | None = None
    validator_reasons: list[str] = Field(default_factory=list, max_length=20)
    raw_model_output: str | None = Field(default=None, max_length=2_000)


class AnswerEvaluation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    technical_substance: Literal[
        "surface", "partial", "deep", "incorrect", "not_applicable"
    ] = "not_applicable"
    key_facts_stated: list[str] = Field(default_factory=list, max_length=20)
    reasoning: str = Field(default="", max_length=500)
    matches_evidence_expected: bool = False
    needs_clarification: bool = False
    factually_correct: bool = True
    slots_demonstrated: list[str] = Field(default_factory=list, max_length=20)
    slots_claimed: list[str] = Field(default_factory=list, max_length=20)
    contradicts_earlier: bool = False


class InterviewAnswerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: str = Field(min_length=4, max_length=64)
    question_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    turn_ids: list[str] = Field(min_length=1, max_length=50)
    status: Literal["waiting", "partial", "answered", "skipped"] = "answered"
    usable: bool = True
    usability: AnswerUsability = "usable"
    final_transcript: str = Field(min_length=0, max_length=20_000)
    answer_evaluation: AnswerEvaluation | None = None
    completed_at: datetime | None = None


class InterviewEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    competency_id: str = Field(min_length=2, max_length=64)
    question_id: str | None = Field(default=None, max_length=64)
    turn_ids: list[str] = Field(min_length=1, max_length=50)
    claim: str = Field(min_length=1, max_length=2_000)
    strength: EvidenceStrength = "partial"
    missing_details: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)


class CompetencyCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_started", "partial", "complete", "insufficient_evidence"] = (
        "not_started"
    )
    required_intents: list[str] = Field(default_factory=list, max_length=20)
    covered_intents: list[str] = Field(default_factory=list, max_length=20)
    missing_intents: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence_states: dict[str, Literal["missing", "claimed", "demonstrated", "confirmed"]] = Field(
        default_factory=dict
    )


class InterviewBrainState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=8, max_length=64)
    definition_id: str = Field(min_length=8, max_length=64)
    state_version: int = Field(ge=0, default=0)
    current_section: InterviewSection = "opening"
    phase_index: int = Field(ge=0, default=0)
    current_competency_id: str | None = Field(default=None, max_length=64)
    current_depth: int = Field(ge=1, le=5, default=1)
    active_question_id: str | None = Field(default=None, max_length=64)
    asked_question_ids: list[str] = Field(default_factory=list, max_length=200)
    candidate_claim_ids: list[str] = Field(default_factory=list, max_length=200)
    coverage: dict[str, CompetencyCoverage] = Field(default_factory=dict)
    consecutive_unusable_answers: int = Field(ge=0, le=20, default=0)
    elapsed_seconds: int = Field(ge=0, default=0)
    last_processed_turn_id: str | None = Field(default=None, max_length=128)
    next_action: NextAction | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class CompetencyScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competency_id: str = Field(min_length=2, max_length=64)
    rating: int | None = Field(default=None, ge=1, le=5)
    outcome: Literal["scored", "not_assessed", "insufficient_evidence"] = "scored"
    anchor: str | None = Field(default=None, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    contradictory_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    missing_intents: list[str] = Field(default_factory=list, max_length=20)
    excerpts: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1, default=0)
    review_required: bool = True


class ScorecardQualityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandatory_coverage_pct: float = Field(ge=0, le=100, default=0)
    repeated_question_rate: float = Field(ge=0, le=1, default=0)
    not_assessed_rate: float = Field(ge=0, le=1, default=0)
    insufficient_evidence_rate: float = Field(ge=0, le=1, default=0)
    validator_failure_rate: float = Field(ge=0, le=1, default=0)
    question_count: int = Field(ge=0, default=0)
    answer_count: int = Field(ge=0, default=0)


class CompetencyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competency_id: str = Field(min_length=2, max_length=64)
    rating: int | None = Field(default=None, ge=1, le=5)
    outcome: Literal["scored", "not_assessed", "insufficient_evidence"] | None = None
    reason: str = Field(min_length=2, max_length=500)


class ScorecardReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "overridden"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    override_reason: str | None = Field(default=None, max_length=2_000)
    competency_overrides: list[CompetencyOverride] = Field(
        default_factory=list, max_length=12
    )

    @model_validator(mode="after")
    def _override_requires_reason(self) -> ScorecardReviewRequest:
        if self.status == "overridden" and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required when status is overridden")
        return self


class ScorecardReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    status: Literal["approved", "overridden"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    override_reason: str | None = Field(default=None, max_length=2_000)
    competency_overrides: list[CompetencyOverride] = Field(
        default_factory=list, max_length=12
    )
    created_at: datetime = Field(default_factory=utc_now)


class InterviewScorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=8, max_length=64)
    definition_id: str = Field(min_length=8, max_length=64)
    competencies: list[CompetencyScore] = Field(min_length=1, max_length=12)
    overall_recommendation: Literal[
        "strong_evidence",
        "meets_expectations",
        "mixed_evidence",
        "insufficient_evidence",
        "human_decision_required",
    ] = "human_decision_required"
    human_review_status: Literal["pending", "approved", "overridden"] = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_at: datetime | None = None
    reviewer_id: str | None = Field(default=None, max_length=128)
    override_reason: str | None = Field(default=None, max_length=2_000)
    next_human_questions: list[str] = Field(default_factory=list, max_length=12)
    quality_metrics: ScorecardQualityMetrics | None = None


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: NextAction
    reason: str = Field(min_length=2, max_length=500)
    competency_id: str | None = Field(default=None, max_length=64)
    intent: str | None = Field(default=None, max_length=64)
    depth: int | None = Field(default=None, ge=1, le=5)
    scenario_id: str | None = Field(default=None, max_length=64)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=4, max_length=2_000)
    competency_id: str | None = Field(default=None, max_length=64)
    intent: str = Field(min_length=2, max_length=64)
    depth: int = Field(ge=1, le=5, default=1)
    source_claim_ids: list[str] = Field(default_factory=list, max_length=20)


class PublicationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=64)
    message: str = Field(min_length=2, max_length=500)
    field: str | None = Field(default=None, max_length=120)


class PublicationValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    issues: list[PublicationIssue] = Field(default_factory=list)
