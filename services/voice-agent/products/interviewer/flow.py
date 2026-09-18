"""Provider-neutral interview question flow."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Protocol

from products.interviewer.coverage import (
    apply_coverage,
    classify_live_answer,
    competency_by_id,
    first_incomplete_competency,
    init_coverage,
    ladder_steps,
    required_intents_for,
)
from products.interviewer.policy import (
    classify_answer_usability,
    decide_next_action,
    non_answer_bounds_from_definition,
    outline_from_definition,
    policy_prompt_block,
    time_bounds_from_definition,
    PolicyDecision,
    PolicyState,
)
from products.interviewer.prompts import (
    OPENING_INSTRUCTIONS_V2,
    TURN_INSTRUCTIONS_V2,
    claim_brief,
    framing_notes,
    prompt_pack,
)
from products.interviewer.validator import (
    GeneratedQuestion,
    ladder_fallback_question,
    parse_generated_question,
    validate_generated_question,
)

logger = logging.getLogger("voice-agent.aaptor")

MAX_PROBES_PER_PHASE = int(os.getenv("MAX_PROBES_PER_PHASE", "8"))
FALLBACK_OPENING = (
    "Hi — thanks for coming in. I'm Aaptor, and I'll be speaking with you today. "
    "Who are you, and what work from the last couple of years are you most proud of?"
)
CLOSING_MESSAGE = (
    "Thank you for your time and for sharing your experience. "
    "This concludes the interview."
)
FALLBACK_FOLLOWUP = (
    "What was the hardest decision on that work, and what would have gone wrong "
    "if you chose the other option?"
)
FALLBACK_FOLLOWUP_NEUTRAL = (
    "Thank you. Could you share one specific example of work you personally "
    "handled, and what happened as a result?"
)

INTERVIEWER_SYSTEM = """You are Aaptor, a senior technical interviewer speaking live. Behave like a thoughtful human in the room, not a script or a form. Invent every spoken line yourself from the materials below.

How you interview:
- Listen to the candidate's last answer as a whole story (what they did, why, how, what happened). Do not pick a keyword and bounce it back.
- Project questions must come from BOTH that last answer and the resume facts for the current project. If they skipped a resume detail, ask how it fits what they just said. If they already covered it, go one layer deeper in their answer.
- Keep this order, without announcing it: intro, then resume projects one by one, then job skills as their own questions (not hung on a project), then DSA as standalone algorithm/coding questions if the job needs it, then role-fit only if time remains.
- One or two questions per project or skill, then ADVANCE to the next uncovered item. Do not keep circling the same project. Skills and DSA are independent of projects. If CURRENT SECTION is jd_requirement and the topic is DSA, invent a coding or algorithm question. Do not mention their projects. Do not connect it to a project.
- Transitions should feel like a person changing subject, not a labeled next round. Do not say moving on, next section, walk me through, you mentioned, tell me more, or what challenges.
- Invent a new question every turn. Do not repeat or rephrase a question you already asked.
- Speak simply, one or two sentences. No markdown. Never say phase, outline, probe, or advance.
- Do not invent employers, projects, or skills. Anti-bias: no age, family, nationality, or health.

If Follow-ups on this thread is 1 or more, ADVANCE. Ask about the next uncovered project, skill, or DSA item — not another angle on the same one.

CURRENT SECTION: {intent}
CURRENT PROJECT OR TOPIC: {focus_item}
AGENDA (internal only — do not read this aloud):
{agenda}
Time: about {target_minutes} minutes total, {elapsed_minutes} elapsed, {remaining_minutes} left. Follow-ups on this thread: {probe_count}. Later: {next_phase}

{resume_brief}

Resume facts for the current project ({focus_item}):
{resume_project_context}

Job description:
{jd_excerpt}

Role competencies: {competencies}
Job skills still missing: {uncovered_skills}
DSA still missing: {uncovered_dsa}
Projects still missing: {uncovered_projects}
Projects already touched: {covered_projects}

Recent candidate answers:
{recent_turns}

Questions you already asked:
{recent_questions}

Last candidate answer:
{last_turn}

Choose PROBE only for the first follow-up on this topic. Otherwise ADVANCE to the next uncovered project, skill, or DSA item.

Output format (strict):
Line 1: DECISION: probe
or
Line 1: DECISION: advance
Then a blank line, then the spoken words only.
"""

STAGE2_SYSTEM = INTERVIEWER_SYSTEM

OPENING_SYSTEM = """You are Aaptor, a live technical interviewer. Invent a short, warm opening in your own words. Do not use a memorized script.

{resume_brief}

Job description:
{jd_excerpt}

Greet them, say you are the interviewer, and invite a natural introduction — who they are and the work they are proud of. Do not start grilling a project yet. Two or three short spoken sentences. No markdown. Do not invent projects.

Output the spoken words only. No DECISION line.
"""


class LlmClient(Protocol):
    async def generate_reply(self, messages: list[dict], **kwargs) -> str: ...


_SECTION_HEADINGS = re.compile(
    r"(?im)^\s*(projects?|key projects|selected projects|academic projects|"
    r"personal projects|work experience|professional experience|experience)\s*:?\s*$"
)
_NEXT_HEADING = re.compile(
    r"(?im)^\s*(education|skills|technical skills|certifications|awards|"
    r"publications|summary|objective|interests|languages|competencies)\s*:?\s*$"
)
_PROJECT_LABEL = re.compile(
    r"(?i)^\s*(?:project(?:\s+name)?|title)\s*[:\-–]\s*(.+)$"
)
_INLINE_PROJECTS = re.compile(r"(?i)^\s*projects?\s*[:\-–]\s+(.+)$")
_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+(.+)$")


def clip_source_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "(not provided)"
    if len(cleaned) <= limit:
        return cleaned
    trimmed = cleaned[: limit - 1].rsplit(" ", 1)[0]
    return f"{trimmed}…"


def _project_title(raw: str) -> str:
    text = " ".join((raw or "").split())
    if not text:
        return ""
    text = re.split(r"\s[:|–—-]\s", text, maxsplit=1)[0]
    text = text.split(":")[0].strip(" •-\t")
    words = text.split()
    if len(words) > 8:
        text = " ".join(words[:8])
    if len(text) > 80:
        text = text[:79].rsplit(" ", 1)[0]
    return text.strip(" .,;/")


def extract_resume_projects(resume_text: str) -> list[str]:
    lines = (resume_text or "").splitlines()
    titles: list[str] = []
    in_section = False
    for line in lines:
        if _SECTION_HEADINGS.match(line):
            in_section = True
            continue
        inline = _INLINE_PROJECTS.match(line)
        if inline:
            rest = re.split(
                r"(?i)\b(skills|education|experience|certifications)\b",
                inline.group(1),
                maxsplit=1,
            )[0]
            for part in re.split(r"[;•]|\s+\|\s+", rest):
                title = _project_title(part)
                if title and title.lower() not in {"project", "projects"}:
                    titles.append(title)
            continue
        if in_section and _NEXT_HEADING.match(line):
            in_section = False
            continue
        labeled = _PROJECT_LABEL.match(line)
        if labeled:
            title = _project_title(labeled.group(1))
            if title:
                titles.append(title)
            continue
        if in_section:
            bullet = _BULLET.match(line)
            candidate = bullet.group(1) if bullet else line.strip()
            title = _project_title(candidate)
            if title and not _NEXT_HEADING.match(title):
                titles.append(title)
    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        key = title.lower()
        if key in seen or key in {"project", "projects"}:
            continue
        seen.add(key)
        unique.append(title)
        if len(unique) >= 12:
            break
    return unique


<<<<<<< HEAD
INTENT_VALUES = {"intro", "resume_project", "jd_requirement", "role_fit"}
_JD_TOPIC_PATTERNS = (
    (
        re.compile(
            r"\b(dsa|data[- ]structures?(?:\s+and\s+algorithms?)?|"
            r"algorithms?|leetcode|coding (?:round|interview|problem)s?)\b",
            re.I,
        ),
        "DSA",
    ),
    (re.compile(r"\bsystem design\b", re.I), "System design"),
    (re.compile(r"\b(sql|postgresql|mysql)\b", re.I), "SQL"),
)


def is_dsa_topic(name: str) -> bool:
    blob = (name or "").lower()
    return any(
        token in blob
        for token in (
            "dsa",
            "algorithm",
            "data structure",
            "leetcode",
            "coding round",
            "coding problem",
        )
    )


def order_job_topics(names: list[str]) -> list[str]:
    skills = [item for item in names if not is_dsa_topic(item)]
    dsa = [item for item in names if is_dsa_topic(item)]
    return skills + dsa


def infer_phase_intent(phase: dict) -> str:
    listed = str(phase.get("intent") or "").strip().lower()
    if listed in INTENT_VALUES:
        return listed
    blob = (
        f"{phase.get('name') or ''} {' '.join(phase.get('topics') or [])}"
    ).lower()
    source = str(phase.get("source") or "").lower()
    if any(token in blob for token in ("warm", "intro", "opening")):
        return "intro"
    if any(token in blob for token in ("role", "fit", "behav", "motiv", "close")):
        return "role_fit"
    if "project" in blob or source == "resume":
        return "resume_project"
    return "jd_requirement"


def extract_jd_requirements(
    job_description: str, competencies: list[str] | None = None
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        key = (label or "").strip()
        if not key or key.lower() in seen:
            return
        seen.add(key.lower())
        found.append(key)

    for item in competencies or []:
        add(str(item))
    text = job_description or ""
    for pattern, label in _JD_TOPIC_PATTERNS:
        if pattern.search(text):
            add(label)
    return order_job_topics(found[:12])


def _item_mentioned(name: str, text: str) -> bool:
    blob = (text or "").lower()
    full = (name or "").strip().lower()
    if not full:
        return False
    if full in blob:
        return True
    tokens = [token for token in re.split(r"\W+", full) if len(token) > 3]
    if not tokens:
        return False
    return all(token in blob for token in tokens[:2])


def resume_project_excerpt(resume_text: str, project_name: str, *, limit: int = 900) -> str:
    """Pull resume lines around a named project so follow-ups can use real facts."""
    cleaned = (resume_text or "").strip()
    name = (project_name or "").strip()
    if not cleaned:
        return "(resume not provided)"
    if not name:
        return clip_source_text(cleaned, limit)
    lines = cleaned.splitlines()
    hits: list[int] = []
    for index, line in enumerate(lines):
        if _item_mentioned(name, line):
            hits.append(index)
    if not hits:
        return clip_source_text(cleaned, limit)
    chunks: list[str] = []
    seen: set[int] = set()
    for hit in hits[:3]:
        start = max(0, hit - 1)
        end = min(len(lines), hit + 4)
        for index in range(start, end):
            if index in seen:
                continue
            seen.add(index)
            text = lines[index].strip()
            if text:
                chunks.append(text)
    excerpt = " ".join(chunks)
    return clip_source_text(excerpt, limit) if excerpt else clip_source_text(cleaned, limit)
=======
def build_candidate_profile(
    *,
    resume_text: str = "",
    interview_setup: dict | None = None,
    definition: dict | None = None,
    existing: dict | None = None,
) -> dict:
    if isinstance(existing, dict) and existing.get("claims"):
        profile = dict(existing)
    else:
        claims: list[dict[str, str]] = []
        for index, name in enumerate(extract_resume_projects(resume_text), start=1):
            claims.append(
                {
                    "claim_id": f"claim_project_{index}",
                    "type": "project",
                    "value": name,
                }
            )
        profile_type = "unknown"
        summary = existing.get("experience_summary") if isinstance(existing, dict) else None
        if isinstance(summary, dict) and summary.get("profile_type"):
            profile_type = str(summary.get("profile_type"))
        elif any(token in (resume_text or "").lower() for token in ("student", "b.tech", "bca", "mca", "undergraduate")):
            profile_type = "final_year_student"
        profile = {
            "experience_summary": {"profile_type": profile_type},
            "claims": claims,
            "raw_resume_text": resume_text,
        }
    role = {}
    if isinstance(definition, dict) and isinstance(definition.get("job_intelligence"), dict):
        role = definition["job_intelligence"].get("role") or {}
    setup = interview_setup if isinstance(interview_setup, dict) else {}
    profile["job_target_level"] = (
        str(role.get("target_level") or setup.get("seniority") or "mid").strip() or "mid"
    )
    if not profile.get("experience_summary"):
        profile["experience_summary"] = {"profile_type": "unknown"}
    return profile
>>>>>>> dev


def format_resume_brief(
    resume_text: str,
    *,
    projects: list[str] | None = None,
) -> str:
    cleaned = (resume_text or "").strip()
    if not cleaned:
        return "RESUME BRIEF: (not provided)"
    headline = clip_source_text(cleaned.splitlines()[0], 180)
    named = list(projects or extract_resume_projects(cleaned))
    project_lines = (
        "\n".join(f"- {name}" for name in named)
        if named
        else "- (no named projects parsed; use the excerpt)"
    )
    return (
        "RESUME BRIEF (facts only — do not invent):\n"
        f"Headline: {headline}\n"
        "Projects you must cover with at least one technical question each "
        "before closing, even in a 15-minute interview:\n"
        f"{project_lines}\n"
        "Full resume excerpt:\n"
        f"{clip_source_text(cleaned, 6_000)}"
    )


def source_briefing(
    *,
    job_description: str = "",
    resume_text: str = "",
    competencies: list[str] | None = None,
    projects: list[str] | None = None,
) -> dict[str, str]:
    skills = [item.strip() for item in (competencies or []) if str(item).strip()]
    named = list(projects or extract_resume_projects(resume_text))
    return {
        "jd_excerpt": clip_source_text(job_description, 2_000),
        "resume_excerpt": clip_source_text(resume_text, 6_000),
        "resume_brief": format_resume_brief(resume_text, projects=named),
        "competencies": ", ".join(skills) if skills else "(none listed)",
        "project_list": ", ".join(named) if named else "(none parsed)",
    }


def phase_topics(phase: dict) -> str:
    topics = phase.get("topics") or []
    return ", ".join(topics) if topics else "(none listed)"


def parse_stage2(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    decision = "probe"
    match = re.search(r"DECISION:\s*(probe|advance)", text, flags=re.IGNORECASE)
    if match:
        decision = match.group(1).lower()
        text = text[match.end() :].lstrip(" \t:-").lstrip("\n").strip()
    text = re.sub(
        r"^DECISION:\s*(probe|advance)\s*", "", text, flags=re.IGNORECASE
    ).strip()
    if not text:
        text = FALLBACK_OPENING
    return decision, text


class SpokenQuestionStream:
    """Strip the DECISION line from a streaming Stage-2 completion."""

    def __init__(self) -> None:
        self.buffer = ""
        self.decision: str | None = None
        self._speech_emitted = 0

    def push(self, delta: str) -> str:
        self.buffer += delta or ""
        match = re.search(r"DECISION:\s*(probe|advance)", self.buffer, flags=re.IGNORECASE)
        if match:
            rest = self.buffer[match.end() :]
            newline = rest.find("\n")
            if newline < 0:
                return ""
            self.decision = match.group(1).lower()
            speech = rest[newline + 1 :].lstrip()
        else:
            stripped = self.buffer.lstrip()
            if re.match(r"DECISION", stripped, flags=re.IGNORECASE) or (
                stripped
                and "DECISION".startswith(stripped[:8].upper())
                and len(stripped) < 24
            ):
                return ""
            speech = stripped
        if len(speech) <= self._speech_emitted:
            return ""
        extra = speech[self._speech_emitted :]
        self._speech_emitted = len(speech)
        return extra

    def finish(self) -> str:
        if self._speech_emitted:
            return ""
        _, question = parse_stage2(self.buffer)
        return question


class InterviewFlow:
    """State and question generation independent of LiveKit transport."""

    def __init__(
        self,
        outline: dict,
        llm_client: LlmClient,
        *,
        max_probes_per_phase: int = MAX_PROBES_PER_PHASE,
        initial_phase_index: int = 0,
        initial_probe_count: int = 0,
        candidate_turns: list[str] | None = None,
        job_description: str = "",
        resume_text: str = "",
        competencies: list[str] | None = None,
        min_turns_before_close: int | None = None,
        interviewer_turns: list[str] | None = None,
        target_duration_minutes: int | None = None,
        interview_definition: dict[str, Any] | None = None,
        candidate_profile: dict[str, Any] | None = None,
        initial_coverage: dict[str, Any] | None = None,
    ) -> None:
        policy_outline = outline_from_definition(interview_definition)
        self.interview_definition = (
            interview_definition if isinstance(interview_definition, dict) else None
        )
        self.policy_mode = bool(policy_outline)
        effective_outline = policy_outline or outline
        self.outline = effective_outline
        self.llm_client = llm_client
        self.max_probes_per_phase = max_probes_per_phase
        self.phases: list[dict] = list(effective_outline.get("phases") or [])
        self.phase_index = max(0, min(initial_phase_index, max(len(self.phases) - 1, 0)))
        self.probe_count = max(0, initial_probe_count)
        self.candidate_turns = list(candidate_turns or [])
        self.interviewer_turns = list(interviewer_turns or [])
        self.job_description = job_description
        self.resume_text = resume_text
        self.competencies = list(competencies or [])
        if self.policy_mode and self.interview_definition:
            names = [
                str(item.get("name") or item.get("id") or "").strip()
                for item in (self.interview_definition.get("competencies") or [])
                if isinstance(item, dict)
            ]
            self.competencies = [name for name in names if name] or self.competencies
        self.resume_projects = extract_resume_projects(resume_text)
<<<<<<< HEAD
        self.jd_requirements = extract_jd_requirements(
            job_description, self.competencies
        )
        self.focus_item = ""
        self._touched_topics: set[str] = set()
=======
        self.candidate_profile = build_candidate_profile(
            resume_text=resume_text,
            interview_setup=None,
            definition=self.interview_definition,
            existing=candidate_profile,
        )
        self.coverage = (
            dict(initial_coverage)
            if isinstance(initial_coverage, dict) and initial_coverage
            else init_coverage(self.interview_definition)
        )
>>>>>>> dev
        self.completed = False
        self.started_at = time.monotonic()
        self.phase_started_at = self.started_at
        self.consecutive_unusable = 0
        self.last_policy_decision: PolicyDecision | None = None
        self.last_answer_usability = "usable"
        self.last_answer_quality = "partial"
        self.last_question_competency_id: str | None = None
        self.last_question_intent = "opening"
        self.last_question_depth = 1
        self.last_question_claim_ids: list[str] = []
        self.last_raw_model_output: str | None = None
        self.last_validator_ok: bool | None = None
        self.last_validator_reasons: list[str] = []
        bounds = time_bounds_from_definition(self.interview_definition)
        non_answer = non_answer_bounds_from_definition(self.interview_definition)
        self.clarify_after = non_answer["clarify_after"]
        self.rephrase_after = non_answer["rephrase_after"]
        self.change_topic_after = non_answer["change_topic_after"]
        phase_minutes = sum(
            max(int(phase.get("duration_minutes", 0)), 0) for phase in self.phases
        )
        self.target_duration_minutes = max(
            1,
            int(
                target_duration_minutes
                if target_duration_minutes is not None
                else bounds["duration_minutes"]
                if self.policy_mode
                else (phase_minutes or 30)
            ),
        )
        self.max_duration_seconds = (
            bounds["hard_end_seconds"]
            if self.policy_mode
            else self.target_duration_minutes * 60
        )
        self.soft_end_seconds = bounds["soft_end_seconds"]
        self.target_end_seconds = bounds["target_end_seconds"]
        self.min_turns_before_close = (
            min_turns_before_close
            if min_turns_before_close is not None
            else max(8, self.target_duration_minutes // 3)
            if self.policy_mode
            else max(12, self.target_duration_minutes // 2)
        )
        if self.policy_mode:
            # Competency phases carry their own probe ceilings.
            phase_caps = [
                int(phase.get("max_probes") or max_probes_per_phase)
                for phase in self.phases
                if phase.get("competency_id")
            ]
            if phase_caps:
                self.max_probes_per_phase = min(self.max_probes_per_phase, max(phase_caps))

    def current_phase(self) -> dict:
        if not self.phases:
            return {
                "name": "warm-up",
                "duration_minutes": 5,
                "topics": ["background"],
                "source": "generic",
            }
        return self.phases[min(self.phase_index, len(self.phases) - 1)]

    def next_phase(self) -> dict | None:
        next_index = self.phase_index + 1
        if next_index < len(self.phases):
            return self.phases[next_index]
        return None

    def apply_decision(self, decision: str) -> None:
        at_last = self.phase_index >= max(len(self.phases) - 1, 0)
        must_advance = self._should_leave_phase()
        if decision != "advance" and not must_advance:
            self.probe_count += 1
            if self.policy_mode or self.probe_count < self._topic_probe_limit():
                return
            must_advance = True
        if not self.policy_mode and self._rotate_focus():
            return
        if at_last:
            if decision == "advance" or must_advance:
                if self._time_up():
                    self.completed = True
                    logger.info(
                        "interview_completed",
                        extra={
                            "event": "interview_completed",
                            "phase_index": self.phase_index,
                        },
                    )
            else:
                self.probe_count += 1
            return
        next_phase = self.next_phase()
        skip_ahead = False
        if (
            not self.policy_mode
            and next_phase is not None
            and not must_advance
            and self._time_remaining_minutes() > 2
        ):
            next_intent = infer_phase_intent(next_phase)
            if next_intent == "role_fit" and (
                self._uncovered_projects() or self._uncovered_requirements()
            ):
                skip_ahead = True
            elif next_intent == "jd_requirement" and self._uncovered_projects():
                skip_ahead = True
        if skip_ahead:
            self.probe_count += 1
            return
        if decision == "advance" or must_advance:
            previous = self.current_phase().get("name")
            self.phase_index += 1
            self.probe_count = 0
            self.phase_started_at = time.monotonic()
            self.focus_item = ""
            self._ensure_focus(None)
            logger.info(
                "phase_advanced",
                extra={
                    "event": "phase_advanced",
                    "from_phase": previous,
                    "to_phase": self.current_phase().get("name"),
                    "forced": must_advance and decision != "advance",
                    "intent": self._phase_intent(),
                },
            )
            return
        self.probe_count += 1

    def _phase_minutes(self) -> int:
        return max(int(self.current_phase().get("duration_minutes") or 5), 1)

    def _phase_probe_limit(self) -> int:
        if self.policy_mode:
            phase_cap = int(self.current_phase().get("max_probes") or self.max_probes_per_phase)
            return max(1, min(self.max_probes_per_phase, phase_cap))
        flow_limit = max(3, self._phase_minutes() // 2)
        return min(self.max_probes_per_phase, flow_limit)

    def _topic_probe_limit(self) -> int:
        if self._phase_intent() == "resume_project":
            return 2
        return 1

    def _policy_state(self, *, pending_candidate_turn: bool = False) -> PolicyState:
        phase = self.current_phase()
        competency_phases = [
            index
            for index, item in enumerate(self.phases)
            if item.get("competency_id")
        ]
        at_last = (
            not competency_phases
            or self.phase_index >= competency_phases[-1]
        )
        has_uncovered = any(
            index > self.phase_index and item.get("competency_id")
            for index, item in enumerate(self.phases)
        )
        competency_id = (
            str(phase.get("competency_id"))
            if phase.get("competency_id")
            else None
        )
        coverage_entry = self.coverage.get(competency_id) if competency_id else None
        missing = list((coverage_entry or {}).get("missing_intents") or [])
        required = list((coverage_entry or {}).get("required_intents") or [])
        coverage_complete = bool(required) and not missing
        competency_ids = [
            str(item.get("competency_id"))
            for item in self.phases
            if item.get("competency_id")
        ]
        gap_id = first_incomplete_competency(self.coverage, competency_ids)
        return PolicyState(
            candidate_turn_count=len(self.candidate_turns)
            + (1 if pending_candidate_turn else 0),
            interviewer_turn_count=len(self.interviewer_turns),
            phase_index=self.phase_index,
            probe_count=self.probe_count,
            elapsed_seconds=max(0, int(time.monotonic() - self.started_at)),
            consecutive_unusable=self.consecutive_unusable,
            completed=self.completed,
            phase_name=str(phase.get("name") or ""),
            competency_id=competency_id,
            max_depth=int(phase.get("max_depth") or 4),
            max_probes=self._phase_probe_limit(),
            soft_end_seconds=self.soft_end_seconds,
            target_end_seconds=self.target_end_seconds,
            hard_end_seconds=self.max_duration_seconds,
            at_last_competency=at_last,
            has_uncovered_competencies=has_uncovered,
            missing_intents=missing,
            coverage_complete=coverage_complete,
            has_coverage_gaps=bool(gap_id),
            gap_competency_id=gap_id,
            clarify_after=self.clarify_after,
            rephrase_after=self.rephrase_after,
            change_topic_after=self.change_topic_after,
        )

    def _current_policy_decision(
        self, *, pending_candidate_turn: bool = False
    ) -> PolicyDecision | None:
        if not self.policy_mode:
            return None
        decision = decide_next_action(
            self._policy_state(pending_candidate_turn=pending_candidate_turn)
        )
        self.last_policy_decision = decision
        return decision

    def _is_warmup_phase(self) -> bool:
        if self._phase_intent() == "intro":
            return True
        name = str(self.current_phase().get("name") or "").lower()
        return any(
            token in name
            for token in ("warm", "intro", "opening", "map", "candidate")
        )

    @staticmethod
    def _is_soft_phase_name(name: str) -> bool:
        lowered = (name or "").lower()
        return any(
            token in lowered
            for token in ("role", "fit", "behav", "motiv", "close", "culture")
        )

    def _phase_intent(self) -> str:
        return infer_phase_intent(self.current_phase())

    def _turn_intent(self, *, is_intro_reply: bool) -> str:
        if is_intro_reply:
            return "intro"
        return self._phase_intent()

    def _is_project_phase(self) -> bool:
        if self._phase_intent() == "resume_project":
            return True
        phase = self.current_phase()
        blob = f"{phase.get('name') or ''} {' '.join(phase.get('topics') or [])}".lower()
        if "project" in blob:
            return True
        return any(project.lower() in blob for project in self.resume_projects)

    def _covered_items(self, names: list[str]) -> list[str]:
        return [name for name in names if name.lower() in self._touched_topics]

    def _uncovered_items(self, names: list[str]) -> list[str]:
        return [name for name in names if name.lower() not in self._touched_topics]

    def _covered_projects(self) -> list[str]:
        return self._covered_items(self.resume_projects)

    def _uncovered_projects(self) -> list[str]:
        return self._uncovered_items(self.resume_projects)

    def _covered_requirements(self) -> list[str]:
        return self._covered_items(self.jd_requirements)

    def _uncovered_requirements(self) -> list[str]:
        return self._uncovered_items(self.jd_requirements)

    def _project_from_text(self, text: str | None) -> str:
        blob = text or ""
        for name in self.resume_projects:
            if _item_mentioned(name, blob):
                return name
        return ""

    def _ensure_focus(self, last_turn: str | None, *, is_intro_reply: bool = False) -> None:
        intent = self._turn_intent(is_intro_reply=is_intro_reply)
        if intent == "intro":
            self.focus_item = (
                self._project_from_text(last_turn)
                or (self._uncovered_projects() or self.resume_projects or ["your recent work"])[0]
            )
            return
        if intent == "resume_project":
            if self.focus_item and self.focus_item.lower() not in self._touched_topics:
                return
            uncovered = self._uncovered_projects()
            named = self._project_from_text(last_turn)
            if named and named in uncovered:
                self.focus_item = named
                return
            self.focus_item = (
                uncovered or self.resume_projects or [self.focus_item or "this project"]
            )[0]
            return
        if intent == "jd_requirement":
            if self.focus_item and self.focus_item.lower() not in self._touched_topics:
                return
            uncovered = (
                self._uncovered_items(self._skill_requirements())
                or self._uncovered_items(self._dsa_requirements())
            )
            self.focus_item = (
                uncovered or self.jd_requirements or ["this job requirement"]
            )[0]
            return
        self.focus_item = "why this role fits your experience"

    def _rotate_focus(self) -> bool:
        if self.focus_item:
            self._touched_topics.add(self.focus_item.lower())
        intent = self._phase_intent()
        if intent == "resume_project":
            remaining = [
                name
                for name in self._uncovered_projects()
                if name.lower() != (self.focus_item or "").lower()
            ]
            if remaining and self._time_remaining_minutes() > 2:
                self.focus_item = remaining[0]
                self.probe_count = 0
                return True
        if intent == "jd_requirement":
            remaining = [
                name
                for name in (
                    self._uncovered_items(self._skill_requirements())
                    + self._uncovered_items(self._dsa_requirements())
                )
                if name.lower() != (self.focus_item or "").lower()
            ]
            if remaining and self._time_remaining_minutes() > 2:
                self.focus_item = remaining[0]
                self.probe_count = 0
                return True
        return False

    def _skill_requirements(self) -> list[str]:
        return [name for name in self.jd_requirements if not is_dsa_topic(name)]

    def _dsa_requirements(self) -> list[str]:
        return [name for name in self.jd_requirements if is_dsa_topic(name)]

    def _agenda_text(self) -> str:
        projects = ", ".join(self.resume_projects) or "(none parsed)"
        skills = ", ".join(self._skill_requirements()) or "(none parsed from JD)"
        dsa = ", ".join(self._dsa_requirements()) or "(none — skip this section)"
        return (
            "1. Intro — candidate background.\n"
            f"2. Resume projects, one by one (project context only): {projects}\n"
            f"3. Required job skills, independent of those projects: {skills}\n"
            f"4. DSA / algorithms as standalone questions, not about a project: {dsa}\n"
            "5. Role fit only if time remains."
        )

    def _time_remaining_minutes(self) -> int:
        return max(0, self.target_duration_minutes - self._elapsed_minutes())

    def _elapsed_minutes(self) -> int:
        return max(0, int((time.monotonic() - self.started_at) / 60))

    def _remember_question(self, question: str) -> None:
        text = (question or "").strip()
        if text and text != CLOSING_MESSAGE:
            self.interviewer_turns.append(text)

    def _ready_to_close(self) -> bool:
        return self._time_up() and len(self.candidate_turns) >= self.min_turns_before_close


    def _too_early_to_advance(self) -> bool:
        if self._is_warmup_phase():
            return False
        if self._should_leave_phase():
            return False
        return self.probe_count < 1

    def _normalize_decision(self, decision: str, *, is_intro_reply: bool) -> str:
        if self.policy_mode:
            policy = self._current_policy_decision()
            if policy is not None:
                if policy.forced_flow_decision == "close":
                    self.completed = True
                    return "advance"
                if not policy.allow_llm_decision:
                    return policy.forced_flow_decision
                # LLM may choose probe/advance, but never skip forced advance.
                if policy.forced_flow_decision == "advance":
                    return "advance"
                if self._should_leave_phase():
                    return "advance"
                return decision if decision in {"probe", "advance"} else "probe"
        if is_intro_reply:
            return "probe"
        if self._too_early_to_advance():
            return "probe"
        if self._should_leave_phase():
            return "advance"
        return decision

    def _apply_turn_decision(self, decision: str, *, is_intro_reply: bool) -> None:
        if is_intro_reply and not self.policy_mode:
            self.probe_count += 1
            return
        self.apply_decision(decision)

    def _should_leave_phase(self) -> bool:
        if self.policy_mode:
<<<<<<< HEAD
=======
            competency_id = self.current_phase().get("competency_id")
            if not competency_id:
                return self.probe_count >= min(2, self.max_probes_per_phase)
            missing = list((self.coverage.get(str(competency_id)) or {}).get("missing_intents") or [])
            if missing and self.probe_count < self._phase_probe_limit():
                return False
            if not missing and self.probe_count >= 1:
                return True
>>>>>>> dev
            return self.probe_count >= self._phase_probe_limit()
        if self._is_warmup_phase():
            return self.probe_count >= 1
        remaining_topics = (
            self._uncovered_projects()
            if self._is_project_phase()
            else self._uncovered_items(self._skill_requirements())
            + self._uncovered_items(self._dsa_requirements())
            if self._phase_intent() == "jd_requirement"
            else []
        )
        if remaining_topics and self._time_remaining_minutes() > 2:
            return self.probe_count >= self._phase_probe_limit()
        phase_elapsed = time.monotonic() - self.phase_started_at
        return (
            self.probe_count >= self._topic_probe_limit()
            or phase_elapsed >= self._phase_minutes() * 60
        )

    def _time_up(self) -> bool:
        return time.monotonic() - self.started_at >= self.max_duration_seconds

    def _soft_time_reached(self) -> bool:
        return time.monotonic() - self.started_at >= self.soft_end_seconds

    def _closing_speech(self, last_candidate_turn: str | None) -> str | None:
        if self.completed:
            return CLOSING_MESSAGE
        if self.policy_mode:
            policy = self._current_policy_decision()
            if policy and policy.forced_flow_decision == "close":
                if last_candidate_turn:
                    usability = classify_answer_usability(last_candidate_turn)
                    if usability == "usable":
                        self.consecutive_unusable = 0
                    elif usability not in {"silence", "stt_failure", "network_failure"}:
                        self.consecutive_unusable += 1
                    self.candidate_turns.append(last_candidate_turn.strip())
                self.completed = True
                return CLOSING_MESSAGE
        if self._time_up():
            if last_candidate_turn:
                self.candidate_turns.append(last_candidate_turn.strip())
            self.completed = True
            return CLOSING_MESSAGE
        return None

<<<<<<< HEAD
    def _resume_project_context(self) -> str:
        return resume_project_excerpt(self.resume_text, self.focus_item)

    def _user_turn_content(self, last_candidate_turn: str, *, is_intro_reply: bool) -> str:
        previous = self.interviewer_turns[-1] if self.interviewer_turns else ""
        earlier = self.candidate_turns[-3:]
        parts = []
        if is_intro_reply:
            parts.append("The candidate just introduced themselves. Use the whole intro.")
        if previous:
            parts.append(f"Your previous question:\n{previous}")
        if earlier:
            parts.append(
                "Earlier answers in this thread:\n"
                + "\n".join(f"- {turn}" for turn in earlier)
            )
        parts.append(f"Latest answer, in full:\n{last_candidate_turn.strip()}")
        if self._phase_intent() in {"intro", "resume_project"} or is_intro_reply:
            parts.append(
                f"Resume facts for {self.focus_item or 'this project'}:\n"
                f"{self._resume_project_context()}"
            )
        return "\n\n".join(parts)
=======
    def _record_answer_quality(self, last_candidate_turn: str, *, is_intro_reply: bool) -> None:
        competency_id = (
            str(self.current_phase().get("competency_id"))
            if self.current_phase().get("competency_id")
            else None
        )
        competency = competency_by_id(self.interview_definition, competency_id)
        required = required_intents_for(self.interview_definition, competency_id)
        usability, quality, covered = classify_live_answer(
            last_candidate_turn,
            required_intents=required,
            evidence_expected=list(competency.get("evidence_expected") or []),
            min_words=1 if is_intro_reply else 3,
        )
        self.last_answer_usability = usability
        self.last_answer_quality = quality
        if usability == "usable":
            self.consecutive_unusable = 0
        elif usability not in {"silence", "stt_failure", "network_failure"}:
            self.consecutive_unusable += 1
        if self.policy_mode and competency_id:
            apply_coverage(
                self.coverage,
                competency_id=competency_id,
                covered_intents=covered,
                evidence_id=f"ev_{self.last_question_competency_id or competency_id}_{len(self.candidate_turns)}",
            )

    def _remember_generated(self, generated: GeneratedQuestion, policy: PolicyDecision | None) -> None:
        self.last_question_competency_id = generated.competency_id or (
            policy.competency_id if policy else None
        )
        self.last_question_intent = generated.intent or (policy.intent if policy else "live_question")
        self.last_question_depth = generated.depth
        self.last_question_claim_ids = list(generated.source_claim_ids)

    def _capture_replay(self, raw: str, *, validator_ok: bool | None, reasons: list[str] | None = None) -> None:
        self.last_raw_model_output = (raw or "")[:2000] or None
        self.last_validator_ok = validator_ok
        self.last_validator_reasons = list(reasons or [])

    def _job_target_level(self) -> str:
        return str(self.candidate_profile.get("job_target_level") or "mid")

    def _profile_type(self) -> str:
        summary = self.candidate_profile.get("experience_summary")
        if isinstance(summary, dict):
            return str(summary.get("profile_type") or "unknown")
        return "unknown"

    def _allowed_probes(self) -> list[str]:
        if not self.interview_definition:
            return []
        probes = self.interview_definition.get("allowed_probes") or []
        return [str(item).strip() for item in probes if str(item).strip()]

    def _prompt_version(self) -> str:
        if isinstance(self.interview_definition, dict):
            return str(self.interview_definition.get("prompt_version") or "interviewer-system-v2")
        return "interviewer-system-v2"

    def _structured_system_prompt(
        self, last_candidate_turn: str | None, policy: PolicyDecision | None
    ) -> tuple[str, str]:
        decision = policy or self._current_policy_decision(
            pending_candidate_turn=bool(last_candidate_turn)
        )
        competency_id = decision.competency_id if decision else None
        competency = competency_by_id(self.interview_definition, competency_id)
        steps = ladder_steps(self.interview_definition, competency_id)
        intent = (decision.intent if decision else "opening") or "opening"
        objective = next(
            (
                str(step.get("objective") or "")
                for step in steps
                if str(step.get("intent") or "") == intent
            ),
            "",
        )
        missing = list((self.coverage.get(competency_id) or {}).get("missing_intents") or [])
        role = {}
        if isinstance(self.interview_definition, dict):
            intelligence = self.interview_definition.get("job_intelligence")
            if isinstance(intelligence, dict):
                role = intelligence.get("role") or {}
        briefing = {
            "action": decision.action if decision else "OPEN_INTERVIEW",
            "intent": intent,
            "section": decision.section if decision else "opening",
            "current_depth": decision.current_depth if decision else 1,
            "max_depth": decision.max_depth if decision else 1,
            "forced_flow_decision": decision.forced_flow_decision if decision else "probe",
            "reason": decision.reason if decision else "open the interview",
            "target_minutes": self.target_duration_minutes,
            "elapsed_minutes": self._elapsed_minutes(),
            "remaining_minutes": self._time_remaining_minutes(),
            "competency_name": str(competency.get("name") or "general"),
            "competency_id": competency_id or "",
            "competency_definition": str(competency.get("definition") or "job-related work"),
            "ladder_objective": objective or "Ask one job-related question.",
            "missing_intents": ", ".join(missing) or "(none)",
            "evidence_expected": ", ".join(
                str(item) for item in (competency.get("evidence_expected") or [])[:6]
            )
            or "(use the last answer)",
            "allowed_probes": "; ".join(self._allowed_probes()) or "(STAR probes)",
            "job_target_level": self._job_target_level(),
            "candidate_framing": self._profile_type(),
            "claim_brief": claim_brief(self.candidate_profile),
            "jd_excerpt": clip_source_text(self.job_description, 2_000),
            "recent_turns": "\n".join(f"- {turn}" for turn in self.candidate_turns[-2:])
            or "(none yet)",
            "recent_questions": "\n".join(f"- {q}" for q in self.interviewer_turns[-8:])
            or "(none yet)",
            "last_turn": last_candidate_turn or "(interview opening)",
            "framing_notes": framing_notes(self._profile_type(), self._job_target_level()),
            "role_title": str(role.get("title") or ""),
        }
        system = prompt_pack(self._prompt_version())
        if last_candidate_turn:
            return system + "\n\n" + TURN_INSTRUCTIONS_V2.format(**briefing), last_candidate_turn
        return system + "\n\n" + OPENING_INSTRUCTIONS_V2.format(**briefing), (
            "Open the interview in your own words and invite them to introduce themselves."
        )

    def _fallback_spoken_question(self, policy: PolicyDecision | None) -> str:
        intent = policy.intent if policy else "opening"
        competency_id = policy.competency_id if policy else None
        if not self.policy_mode:
            return FALLBACK_FOLLOWUP
        return ladder_fallback_question(
            self.interview_definition,
            competency_id=competency_id,
            intent=intent,
        )

    def _coerce_generated(
        self,
        raw: str,
        *,
        policy: PolicyDecision | None,
        last_candidate_turn: str | None,
    ) -> GeneratedQuestion:
        parsed = parse_generated_question(raw)
        if parsed is None:
            _, spoken = parse_stage2(raw)
            parsed = GeneratedQuestion(
                question=spoken,
                competency_id=policy.competency_id if policy else None,
                intent=policy.intent if policy else "live_question",
                depth=policy.current_depth if policy else 1,
            )
        result = validate_generated_question(
            parsed,
            definition=self.interview_definition,
            policy_competency_id=policy.competency_id if policy else None,
            policy_intent=policy.intent if policy else parsed.intent,
            policy_depth=policy.current_depth if policy else parsed.depth,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
        )
        self._capture_replay(raw, validator_ok=result.ok, reasons=result.reasons)
        if result.ok:
            return result.question
        logger.info(
            "question_validation_failed",
            extra={
                "event": "question_validation_failed",
                "reasons": result.reasons,
                "prompt_version": self._prompt_version(),
            },
        )
        fallback = self._fallback_spoken_question(policy)
        return GeneratedQuestion(
            question=fallback,
            competency_id=policy.competency_id if policy else None,
            intent=policy.intent if policy else "live_question",
            depth=policy.current_depth if policy else 1,
        )
>>>>>>> dev

    def _prompt_for_turn(
        self, last_candidate_turn: str | None
    ) -> tuple[str, str]:
        if self.policy_mode:
            return self._structured_system_prompt(
                last_candidate_turn,
                self._current_policy_decision(
                    pending_candidate_turn=bool(last_candidate_turn)
                ),
            )
        phase = self.current_phase()
        next_phase = self.next_phase()
        next_phase_label = (
            f"{next_phase.get('name')} — topics: {phase_topics(next_phase)}"
            if next_phase
            else "none (closing)"
        )
        recent = self.candidate_turns[-4:]
        recent_questions = self.interviewer_turns[-8:]
        briefing = source_briefing(
            job_description=self.job_description,
            resume_text=self.resume_text,
            competencies=self.competencies,
            projects=self.resume_projects,
        )
        coverage = {
            "uncovered_projects": ", ".join(self._uncovered_projects())
            or "(none left)",
            "covered_projects": ", ".join(self._covered_projects()) or "(none yet)",
            "uncovered_skills": ", ".join(
                self._uncovered_items(self._skill_requirements())
            )
            or "(none left)",
            "uncovered_dsa": ", ".join(self._uncovered_items(self._dsa_requirements()))
            or "(none left)",
            "covered_requirements": ", ".join(self._covered_requirements())
            or "(none yet)",
        }
        is_intro_reply = bool(last_candidate_turn) and not self.candidate_turns
        self._ensure_focus(last_candidate_turn, is_intro_reply=is_intro_reply)
        policy = (
            self._current_policy_decision(
                pending_candidate_turn=bool(last_candidate_turn)
            )
            if self.policy_mode
            else None
        )
        policy_block = f"\n{policy_prompt_block(policy)}\n" if policy else ""
        if last_candidate_turn:
            last_turn = last_candidate_turn
            if is_intro_reply:
                last_turn = (
                    "The candidate just introduced themselves:\n"
                    f"{last_candidate_turn}"
                )
            prompt = INTERVIEWER_SYSTEM.format(
                intent=self._phase_intent(),
                focus_item=self.focus_item or phase.get("name", "this topic"),
                agenda=self._agenda_text(),
                probe_count=self.probe_count,
                next_phase=next_phase_label,
                target_minutes=self.target_duration_minutes,
                elapsed_minutes=self._elapsed_minutes(),
                remaining_minutes=self._time_remaining_minutes(),
                recent_turns="\n".join(f"- {turn}" for turn in recent)
                or "(none yet)",
                recent_questions="\n".join(f"- {q}" for q in recent_questions)
                or "(none yet)",
                resume_project_context=self._resume_project_context(),
                last_turn=last_turn,
                **briefing,
                **coverage,
            )
            return policy_block + prompt, self._user_turn_content(
                last_candidate_turn, is_intro_reply=is_intro_reply
            )
        prompt = OPENING_SYSTEM.format(
            **briefing,
        )
        return policy_block + prompt, (
            "Open the interview in your own words and invite them to "
            "introduce themselves."
        )

    async def generate_next_question(self, last_candidate_turn: str | None) -> str:
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        closing = self._closing_speech(last_candidate_turn)
        if closing:
            return closing
<<<<<<< HEAD
=======
        if last_candidate_turn is None:
            started = time.perf_counter()
            opening = FALLBACK_OPENING
            self.last_question_competency_id = None
            self.last_question_intent = "opening"
            self.last_question_depth = 1
            self.last_question_claim_ids = []
            self.last_raw_model_output = None
            self.last_validator_ok = None
            self.last_validator_reasons = []
            self._commit_turn(
                None,
                "probe",
                started=started,
                is_opening=True,
                question=opening,
            )
            return opening
        if last_candidate_turn and self.policy_mode:
            is_intro_reply = not self.candidate_turns
            self._record_answer_quality(
                last_candidate_turn, is_intro_reply=is_intro_reply
            )
>>>>>>> dev
        prompt, user_content = self._prompt_for_turn(last_candidate_turn)

        started = time.perf_counter()
        policy = self.last_policy_decision
        try:
            raw = await self.llm_client.generate_reply(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ]
            )
        except Exception:
            logger.exception(
                "stage2_question_failed",
                extra={"event": "stage2_question_failed"},
            )
            if last_candidate_turn:
                is_intro_reply = not self.candidate_turns
                self.candidate_turns.append(last_candidate_turn)
                self._apply_turn_decision(
                    self._normalize_decision("probe", is_intro_reply=is_intro_reply),
                    is_intro_reply=is_intro_reply,
                )
            fallback = (
                FALLBACK_OPENING
                if last_candidate_turn is None
                else self._fallback_spoken_question(policy)
            )
            if self.completed:
                fallback = CLOSING_MESSAGE
            generated = GeneratedQuestion(
                question=fallback,
                competency_id=policy.competency_id if policy else None,
                intent=policy.intent if policy else "live_question",
                depth=policy.current_depth if policy else 1,
            )
            self._remember_generated(generated, policy)
            self._remember_question(fallback)
            return fallback
        if self.policy_mode:
            generated = self._coerce_generated(
                raw, policy=policy, last_candidate_turn=last_candidate_turn
            )
            parsed = parse_generated_question(raw)
            if parsed is None and generated.question == self._fallback_spoken_question(
                policy
            ):
                try:
                    raw = await self.llm_client.generate_reply(
                        [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_content},
                        ]
                    )
                    generated = self._coerce_generated(
                        raw, policy=policy, last_candidate_turn=last_candidate_turn
                    )
                except Exception:
                    logger.exception(
                        "stage2_question_retry_failed",
                        extra={"event": "stage2_question_retry_failed"},
                    )
            decision, question = generated.decision, generated.question
            self._remember_generated(generated, policy)
        else:
            decision, question = parse_stage2(raw)
        if last_candidate_turn:
            is_intro_reply = not self.candidate_turns
            if not self.policy_mode:
                usability = classify_answer_usability(
                    last_candidate_turn,
                    min_words=1 if is_intro_reply else 3,
                )
                self.last_answer_usability = usability
                if usability == "usable":
                    self.consecutive_unusable = 0
                elif usability not in {"silence", "stt_failure", "network_failure"}:
                    self.consecutive_unusable += 1
            self.candidate_turns.append(last_candidate_turn)
            decision = self._normalize_decision(
                decision, is_intro_reply=is_intro_reply
            )
            self._apply_turn_decision(decision, is_intro_reply=is_intro_reply)
            if self.completed:
                question = CLOSING_MESSAGE
        self._remember_question(question)
        logger.info(
            "stage2_question",
            extra={
                "event": "stage2_question",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "decision": decision,
                "policy_action": (
                    self.last_policy_decision.action
                    if self.last_policy_decision
                    else None
                ),
                "phase": self.current_phase().get("name"),
                "phase_index": self.phase_index,
                "probe_count": self.probe_count,
                "is_opening": last_candidate_turn is None,
            },
        )
        return question

    def _commit_turn(
        self,
        last_candidate_turn: str | None,
        decision: str,
        *,
        started: float,
        is_opening: bool,
        question: str = "",
    ) -> None:
        if last_candidate_turn:
            is_intro_reply = not self.candidate_turns
            if self.policy_mode:
                self._record_answer_quality(
                    last_candidate_turn, is_intro_reply=is_intro_reply
                )
            else:
                usability = classify_answer_usability(
                    last_candidate_turn,
                    min_words=1 if is_intro_reply else 3,
                )
                self.last_answer_usability = usability
                if usability == "usable":
                    self.consecutive_unusable = 0
                elif usability not in {"silence", "stt_failure", "network_failure"}:
                    self.consecutive_unusable += 1
            self.candidate_turns.append(last_candidate_turn)
            decision = self._normalize_decision(
                decision, is_intro_reply=is_intro_reply
            )
            self._apply_turn_decision(decision, is_intro_reply=is_intro_reply)
        self._remember_question(question)
        logger.info(
            "stage2_question",
            extra={
                "event": "stage2_question",
                "stage": "llm",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "decision": decision,
                "policy_action": (
                    self.last_policy_decision.action
                    if self.last_policy_decision
                    else None
                ),
                "phase": self.current_phase().get("name"),
                "phase_index": self.phase_index,
                "probe_count": self.probe_count,
                "is_opening": is_opening,
            },
        )

    async def _iter_opening_speech(self, stream, prompt: str, user_content: str):
        pending = ""
        started_speech = False
        async for delta in stream(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ]
        ):
            pending += delta or ""
            if not started_speech:
                match = re.search(
                    r"DECISION:\s*(probe|advance)\s*\n+",
                    pending,
                    flags=re.IGNORECASE,
                )
                if match:
                    pending = pending[match.end() :]
                    started_speech = True
                elif re.match(r"\s*DECISION", pending, flags=re.IGNORECASE):
                    continue
                else:
                    started_speech = True
            if started_speech and pending:
                yield pending
                pending = ""
        if pending:
            yield pending

    async def generate_next_question_stream(self, last_candidate_turn: str | None):
        if self.policy_mode:
            yield await self.generate_next_question(last_candidate_turn)
            return
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        closing = self._closing_speech(last_candidate_turn)
        if closing:
            yield closing
            return

        stream = getattr(self.llm_client, "generate_reply_stream", None) or getattr(
            self.llm_client, "stream_reply", None
        )
        if stream is None:
            yield await self.generate_next_question(last_candidate_turn)
            return

        prompt, user_content = self._prompt_for_turn(last_candidate_turn)
        started = time.perf_counter()
        is_opening = last_candidate_turn is None
        parser = SpokenQuestionStream()
        spoken_parts: list[str] = []
        try:
            if is_opening:
                async for spoken in self._iter_opening_speech(
                    stream, prompt, user_content
                ):
                    spoken_parts.append(spoken)
                    yield spoken
            else:
                async for delta in stream(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ]
                ):
                    spoken = parser.push(delta)
                    if spoken:
                        spoken_parts.append(spoken)
                        yield spoken
                leftover = parser.finish()
                if leftover:
                    spoken_parts.append(leftover)
                    yield leftover
        except Exception:
            logger.exception(
                "stage2_question_failed",
                extra={"event": "stage2_question_failed"},
            )
        question = "".join(spoken_parts).strip()
        if not question:
            question = FALLBACK_OPENING if is_opening else FALLBACK_FOLLOWUP
            yield question
        self._commit_turn(
            last_candidate_turn,
            parser.decision or "probe",
            started=started,
            is_opening=is_opening,
            question=question,
        )
