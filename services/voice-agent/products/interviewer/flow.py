"""Provider-neutral interview question flow."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Protocol

from products.interviewer.latency import PUBLISHED_CONTEXT_LIMIT_CHARS
from products.interviewer.coverage import (
    apply_coverage,
    classify_live_answer,
    competency_by_id,
    evidenced_intents,
    first_incomplete_competency,
    init_coverage,
    ladder_steps,
    mark_intent_asked,
    mark_missing_intents_insufficient,
    quality_from_evaluation,
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
from products.interviewer.evidence import (
    build_ledger,
    difficulty_profile,
    ledger_brief,
    promote,
    target_slot_brief,
)
from products.interviewer.prompts import (
    OPENING_INSTRUCTIONS_V2,
    TURN_INSTRUCTIONS_V2,
    action_phrasing_note,
    claim_brief,
    framing_notes,
    prompt_pack,
)
from products.interviewer.validator import (
    SKIP_HOOK_INTENTS,
    GeneratedQuestion,
    extract_hook_fact,
    ladder_fallback_question,
    next_probe_shape,
    parse_generated_question,
    validate_generated_question,
)

logger = logging.getLogger("voice-agent.aaptor")

MAX_PROBES_PER_PHASE = int(os.getenv("MAX_PROBES_PER_PHASE", "8"))


def legacy_decision_flow_enabled() -> bool:
    return os.getenv("ALLOW_LEGACY_INTERVIEW_FLOW", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
FALLBACK_OPENING = (
    "Hi — thanks for coming in. I'm Aaptor, and I'll be speaking with you today. "
    "Who are you, and what work from the last couple of years are you most proud of?"
)
CLOSING_MESSAGE = (
    "Thank you for your time and for sharing your experience. "
    "This concludes the interview."
)
FALLBACK_FOLLOWUP = (
    "What was the hardest decision on that work?"
)
FALLBACK_FOLLOWUP_NEUTRAL = (
    "Thank you. Can you share one concrete example from that work?"
)

# Walked in order when the ladder example for the current intent was already asked.
FALLBACK_PROBE_ROTATION = (
    "What exactly did you change, and what did that number go from and to?",
    "Which parts of that were your call?",
    "Why that approach rather than the obvious alternative?",
    "Where would that approach break, and what changes at ten times the load?",
    "If you had half the time, what would you have cut?",
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
            # A wrapped description continues the previous entry; treating it as
            # its own project produces mid-sentence fragments like
            # "against Stripe payouts, cutting manual reconciliation from 6".
            if not bullet and candidate[:1].islower():
                continue
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

def rank_projects_by_competency_gap(
    claims: list[dict],
    *,
    competencies: list[str] | None = None,
    job_description: str = "",
    coverage: dict | None = None,
) -> list[dict]:
    """Rank resume project/experience claims for interview use (plan §12).

    Prefer claims that match JD/competency tokens and can fill coverage gaps.
    Does not change the job bar — ranking only personalizes order.
    """
    items = [item for item in claims if isinstance(item, dict) and str(item.get("value") or "").strip()]
    if not items:
        return []
    tokens: set[str] = set()
    for raw in list(competencies or []) + [job_description or ""]:
        for piece in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", str(raw).lower()):
            if len(piece) >= 3:
                tokens.add(piece)
    gap_ids: set[str] = set()
    if isinstance(coverage, dict):
        for cid, row in coverage.items():
            if not isinstance(row, dict):
                continue
            missing = row.get("missing_intents") or []
            if missing:
                gap_ids.add(str(cid))
    type_boost = {
        "project": 5,
        "experience": 4,
        "internship": 3,
        "skill": 1,
        "achievement": 2,
    }

    def score(item: dict) -> tuple:
        value = str(item.get("value") or "").lower()
        ctype = str(item.get("type") or "").lower()
        overlap = sum(1 for token in tokens if token in value)
        gap_hit = 1 if any(gid.replace("_", " ") in value for gid in gap_ids) else 0
        ownership = 1 if any(w in value for w in ("i ", "led", "owned", "built", "designed")) else 0
        return (
            overlap * 10 + type_boost.get(ctype, 0) + gap_hit * 3 + ownership,
            -len(value),
        )

    return sorted(items, key=score, reverse=True)


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
    raw_claims = profile.get("claims") if isinstance(profile.get("claims"), list) else []
    competency_names: list[str] = []
    if isinstance(definition, dict):
        for item in definition.get("competencies") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    competency_names.append(name)
    if not competency_names and isinstance(setup, dict):
        raw_skills = setup.get("competencies") or []
        if isinstance(raw_skills, list):
            competency_names = [str(item).strip() for item in raw_skills if str(item).strip()]
    ranked = rank_projects_by_competency_gap(
        [item for item in raw_claims if isinstance(item, dict)],
        competencies=competency_names,
        job_description=str(
            (definition or {}).get("job_description")
            if isinstance(definition, dict)
            else ""
        ),
    )
    if ranked:
        profile["claims"] = ranked
        profile["ranked_claim_ids"] = [
            str(item.get("claim_id"))
            for item in ranked
            if item.get("claim_id")
        ]
    return profile


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


class SpokenJsonQuestionStream:
    """Emit the spoken `question` field from a streaming JSON object."""

    _ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}

    def __init__(self) -> None:
        self.buffer = ""
        self.question = ""
        self._emitted = 0
        self._in_question = False
        self._done = False
        self._start = 0

    def push(self, delta: str) -> str:
        if self._done:
            return ""
        self.buffer += delta or ""
        if not self._in_question:
            match = re.search(r'"question"\s*:\s*"', self.buffer)
            if not match:
                return ""
            self._in_question = True
            self._start = match.end()
        body = self.buffer[self._start :]
        chars: list[str] = []
        escaped = False
        for ch in body:
            if escaped:
                chars.append(self._ESCAPES.get(ch, ch))
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                self._done = True
                break
            chars.append(ch)
        text = "".join(chars)
        extra = text[self._emitted :]
        self._emitted = len(text)
        self.question = text
        return extra

    def finish(self) -> str:
        if self._done or self._emitted >= len(self.question):
            return ""
        extra = self.question[self._emitted :]
        self._emitted = len(self.question)
        return extra

    @property
    def question_complete(self) -> bool:
        """True once the closing quote of the `question` field has arrived."""
        return self._done


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
        allow_legacy_flow: bool | None = None,
    ) -> None:
        if candidate_profile and candidate_profile.get("claims"):
            projects = [
                str(claim.get("value") or "").strip()
                for claim in candidate_profile.get("claims", [])
                if str(claim.get("type")).lower() == "project" and str(claim.get("value")).strip()
            ]
        else:
            projects = extract_resume_projects(resume_text)

        policy_outline = outline_from_definition(
            interview_definition,
            resume_projects=projects,
        )
        self.interview_definition = (
            interview_definition if isinstance(interview_definition, dict) else None
        )
        self.policy_mode = bool(policy_outline)
        self.allow_legacy_flow = (
            legacy_decision_flow_enabled()
            if allow_legacy_flow is None
            else bool(allow_legacy_flow)
        )
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
        self.jd_requirements = extract_jd_requirements(
            job_description, self.competencies
        )
        self.focus_item = ""
        self._touched_topics: set[str] = set()
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
        self.completed = False
        self.started_at = time.monotonic()
        self.phase_started_at = self.started_at
        self.consecutive_unusable = 0
        self.last_policy_decision: PolicyDecision | None = None
        self.last_answer_usability = "usable"
        self.last_answer_quality = "partial"
        self.last_answer_evaluation: dict[str, Any] | None = None
        self.known_facts: dict[str, list[str]] = {}
        self.consecutive_dry_probes = 0
        self.dry_probe_limit = 2
        self.intent_repairs_used: set[str] = set()
        self.last_probe_shape: dict[str, str] = {}
        self.probes_without_gain = 0
        self.contradiction_pending = False
        self.final_addition_offered = False
        self._last_target_sent = ""
        self.difficulty = (difficulty or "applied").strip().lower()
        self.language = (language or "English").strip() or "English"
        self.difficulty_profile = difficulty_profile(self.difficulty)
        self.evidence_ledger = build_ledger(
            self.interview_definition,
            target_level=str(self.candidate_profile.get("job_target_level") or "mid"),
            difficulty=self.difficulty,
        )
        self.last_question_competency_id: str | None = None
        self.last_question_intent = "opening"
        self.last_question_depth = 1
        self.last_question_claim_ids: list[str] = []
        self.last_raw_model_output: str | None = None
        self.last_validator_ok: bool | None = None
        self.last_validator_reasons: list[str] = []
        self.last_hook_fact: str = ""
        bounds = time_bounds_from_definition(self.interview_definition)
        non_answer = non_answer_bounds_from_definition(self.interview_definition)
        self.clarify_after = non_answer["clarify_after"]
        self.rephrase_after = non_answer["rephrase_after"]
        self.change_topic_after = non_answer["change_topic_after"]
        self.close_after_unusable = non_answer["close_after"]
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
            # Competency phases carry their own probe ceilings; the global cap is a
            # backstop, so it must not clamp a recruiter's per-competency setting.
            phase_caps = [
                int(phase.get("max_probes") or max_probes_per_phase)
                for phase in self.phases
                if phase.get("competency_id")
            ]
            if phase_caps:
                self.max_probes_per_phase = max(self.max_probes_per_phase, max(phase_caps))

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
            leaving_id = self.current_phase().get("competency_id")
            if leaving_id:
                mark_missing_intents_insufficient(
                    self.coverage, competency_id=str(leaving_id)
                )
            self.phase_index += 1
            self.probe_count = 0
            self.consecutive_dry_probes = 0
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
        intent = self._phase_intent()
        if intent == "resume_project":
            base = 4
        elif intent == "jd_requirement":
            base = 5
        else:
            base = 3
        return min(base, self.max_probes_per_phase)

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
        ledger_entry = self.evidence_ledger.get(competency_id or "")
        # Named-but-unproven evidence must not close a competency; probe caps and
        # the time guard remain the only other way out.
        evidence_satisfied = ledger_entry is None or ledger_entry.is_satisfied()
        coverage_complete = bool(required) and not missing and evidence_satisfied
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
            consecutive_dry_probes=self.consecutive_dry_probes,
            dry_probe_limit=self.dry_probe_limit,
            clarify_after=self.clarify_after,
            rephrase_after=self.rephrase_after,
            change_topic_after=self.change_topic_after,
            close_after=self.close_after_unusable,
            intent_repair_available=self._intent_repair_available(
                competency_id, missing
            ),
        )

    def _intent_repair_key(self, competency_id: str | None, intent: str | None) -> str:
        return f"{competency_id or ''}::{intent or ''}"

    def _intent_repair_available(
        self, competency_id: str | None, missing: list[str]
    ) -> bool:
        if not competency_id or not missing:
            return False
        return self._intent_repair_key(competency_id, missing[0]) not in self.intent_repairs_used

    def _current_policy_decision(
        self,
        *,
        pending_candidate_turn: bool = False,
        advance_if_ready: bool = False,
    ) -> PolicyDecision | None:
        if not self.policy_mode:
            return None
        decision = decide_next_action(
            self._policy_state(pending_candidate_turn=pending_candidate_turn)
        )
        if advance_if_ready and decision.forced_flow_decision == "advance" and not self.completed:
            # Hop warmup phases (opening → candidate_map → first competency) in one
            # turn so the spoken question is already on a real competency. Never
            # multi-hop across competency phases — that would skip assessment.
            for _ in range(4):
                if decision.forced_flow_decision != "advance" or self.completed:
                    break
                leaving = self.current_phase()
                leaving_is_warmup = not bool(leaving.get("competency_id"))
                self.apply_decision("advance")
                decision = decide_next_action(
                    self._policy_state(pending_candidate_turn=pending_candidate_turn)
                )
                landed = self.current_phase()
                if landed.get("competency_id"):
                    break
                if not leaving_is_warmup:
                    # Left a competency; do not cascade further this turn.
                    break
        self.last_policy_decision = decision
        if decision is not None and decision.intent in {
            "final_addition",
            "closing",
        }:
            # Soft-close used to leave intents stuck at ``asked`` forever — seal
            # asked-but-uncovered assessment intents as assessed_insufficient.
            self._seal_open_competency_gaps()
        if (
            decision is not None
            and "reframed repair" in (decision.reason or "")
            and decision.competency_id
            and decision.intent
        ):
            self.intent_repairs_used.add(
                self._intent_repair_key(decision.competency_id, decision.intent)
            )
            # Give the reframed ask a clean dry-probe counter.
            self.consecutive_dry_probes = 0
        return decision

    def _reprobe_guidance(
        self, *, competency_id: str | None, intent: str, last_candidate_turn: str | None
    ) -> str:
        if not last_candidate_turn:
            return ""
        if (self.last_question_intent or "") != intent:
            return ""
        if (self.last_question_competency_id or None) != (competency_id or None):
            return ""
        detail = (last_candidate_turn or "").strip()
        if len(detail) > 220:
            detail = detail[:217] + "..."
        return (
            "RE-PROBE (same intent as your last question):\n"
            f"- The candidate already answered: {detail}\n"
            "- Do NOT repeat the same ask or the same sentence frame "
            "(e.g. 'Can you describe the specific steps…').\n"
            "- Acknowledge one concrete detail they said, then ask for the "
            "single missing gap: a decision point, failure mode, TTL/limit, "
            "or measured outcome.\n"
        )

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
            competency_id = self.current_phase().get("competency_id")
            if not competency_id:
                return self.probe_count >= min(2, self.max_probes_per_phase)
            missing = list((self.coverage.get(str(competency_id)) or {}).get("missing_intents") or [])
            ledger_entry = self.evidence_ledger.get(str(competency_id))
            if ledger_entry is not None and not ledger_entry.is_satisfied():
                return self.probe_count >= self._phase_probe_limit()
            if missing and self.probe_count < self._phase_probe_limit():
                return False
            if not missing and self.probe_count >= 1:
                return True
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

    def _seal_open_competency_gaps(self) -> None:
        """Mark asked-but-uncovered intents when leaving assessment (close / advance)."""
        competency_id = self.current_phase().get("competency_id")
        if competency_id:
            mark_missing_intents_insufficient(
                self.coverage, competency_id=str(competency_id)
            )

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
                self._seal_open_competency_gaps()
                self.completed = True
                return CLOSING_MESSAGE
        if self._time_up():
            if last_candidate_turn:
                self.candidate_turns.append(last_candidate_turn.strip())
            self._seal_open_competency_gaps()
            self.completed = True
            return CLOSING_MESSAGE
        return None

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

    def _record_answer_quality(
        self,
        last_candidate_turn: str,
        *,
        is_intro_reply: bool,
        answer_eval: Any | None = None,
        update_counters: bool = True,
    ) -> None:
        competency_id = (
            str(self.current_phase().get("competency_id"))
            if self.current_phase().get("competency_id")
            else None
        )
        competency = competency_by_id(self.interview_definition, competency_id)
        required = required_intents_for(self.interview_definition, competency_id)
        usability, quality, hinted = classify_live_answer(
            last_candidate_turn,
            required_intents=required,
            evidence_expected=list(competency.get("evidence_expected") or []),
            min_words=1 if is_intro_reply else 3,
        )
        self.last_answer_usability = usability
        # An LLM substance verdict outranks the keyword heuristic when available.
        llm_quality = quality_from_evaluation(answer_eval) if answer_eval else None
        self.last_answer_quality = llm_quality or quality
        covered = evidenced_intents(
            required_intents=required,
            evidence_expected=list(competency.get("evidence_expected") or []),
            answer_eval=answer_eval,
            asked_intent=self.last_question_intent,
            answer_text=last_candidate_turn,
        )
        if answer_eval is not None:
            self._remember_known_facts(competency_id, answer_eval)
        logger.info(
            "answer_quality_evaluated",
            extra={
                "event": "answer_quality_evaluated",
                "llm_substance": getattr(answer_eval, "technical_substance", None)
                if answer_eval is not None
                else None,
                "keyword_quality": quality,
                "applied_quality": self.last_answer_quality,
                "hinted_intents": hinted,
                "evidenced_intents": covered,
                "competency_id": competency_id,
            },
        )
        if update_counters:
            # Off-topic / jailbreak land as usability=off_topic and climb the
            # clarify ladder. Silence / STT / network failures do not.
            if usability == "usable" and quality not in {"off_topic", "unsupported"}:
                self.consecutive_unusable = 0
            elif usability not in {"silence", "stt_failure", "network_failure"}:
                self.consecutive_unusable += 1
        if self.policy_mode and competency_id and usability != "off_topic":
            apply_coverage(
                self.coverage,
                competency_id=competency_id,
                covered_intents=covered,
                evidence_id=(
                    f"ev_{self.last_question_competency_id or competency_id}_"
                    f"{len(self.candidate_turns)}"
                    if covered
                    else None
                ),
                answer_eval=answer_eval,
            )
            after = len(
                (self.coverage.get(competency_id) or {}).get("covered_intents") or []
            )
            gained = (
                bool(moved_slots)
                or after > before
                or len(self.known_facts.get(competency_id, [])) > facts_before
            )
            if gained:
                self.probes_without_gain = 0
            elif update_counters:
                self.probes_without_gain += 1
            if moved_slots:
                logger.info(
                    "evidence_slots_moved",
                    extra={
                        "event": "evidence_slots_moved",
                        "competency_id": competency_id,
                        "slots": moved_slots,
                    },
                )

    def _remember_known_facts(self, competency_id: str | None, answer_eval: Any) -> None:
        if not competency_id:
            return
        facts = getattr(answer_eval, "key_facts_stated", None) or []
        bucket = self.known_facts.setdefault(competency_id, [])
        added = 0
        for fact in facts:
            text = str(fact).strip()
            if text and text not in bucket:
                bucket.append(text)
                added += 1
        if len(bucket) > 8:
            del bucket[:-8]
        # Follow-ups that add no new facts count toward the dry-probe stop rule.
        if self.probe_count > 0 and self.policy_mode:
            if added:
                self.consecutive_dry_probes = 0
            else:
                self.consecutive_dry_probes += 1
                logger.info(
                    "dry_followup",
                    extra={
                        "event": "dry_followup",
                        "competency_id": competency_id,
                        "consecutive_dry_probes": self.consecutive_dry_probes,
                    },
                )

    def _known_facts_brief(self, competency_id: str | None) -> str:
        facts = self.known_facts.get(competency_id or "", [])
        return "\n".join(f"- {fact}" for fact in facts) or "(none yet)"

    def _probe_shape_guidance(self, competency_id: str | None) -> str:
        shape = self.last_probe_shape.get(competency_id or "")
        return shape or "(none yet)"

    def _hook_fact(
        self,
        last_turn: str | None,
        competency_id: str | None,
        intent: str | None = None,
    ) -> str:
        if not last_turn or (intent or "") in SKIP_HOOK_INTENTS:
            return ""
        # Prefer entity/tech nouns from the latest answer over known_facts tails
        # (known_facts often end with weak fillers like "safely").
        from_turn = extract_hook_fact(last_turn)
        if from_turn:
            return from_turn
        facts = self.known_facts.get(competency_id or "", [])
        for fact in reversed(facts):
            candidate = extract_hook_fact(str(fact))
            if candidate:
                return candidate
        return ""

    def _next_probe_shape(
        self, competency_id: str | None, intent: str | None = None
    ) -> str:
        if (intent or "") in SKIP_HOOK_INTENTS:
            return ""
        return next_probe_shape(self.last_probe_shape.get(competency_id or ""))

    def _refine_answer_quality(
        self,
        last_candidate_turn: str | None,
        generated: GeneratedQuestion,
        *,
        asked_intent: str | None = None,
        asked_competency_id: str | None = None,
    ) -> None:
        """Re-score the just-answered turn once the LLM verdict arrives with the next question."""
        answer_eval = generated.answer_evaluation
        if answer_eval is None:
            return
        self.last_answer_evaluation = answer_eval.as_dict()
        self.contradiction_pending = bool(
            getattr(answer_eval, "contradicts_earlier", False)
        )
        if not last_candidate_turn or not self.policy_mode:
            return
        # Temporarily restore the asked intent/competency for coverage credit.
        previous_intent = self.last_question_intent
        previous_competency = self.last_question_competency_id
        if asked_intent:
            self.last_question_intent = asked_intent
        if asked_competency_id:
            self.last_question_competency_id = asked_competency_id
        try:
            # candidate_turns has not been appended yet, so intro detection still holds.
            self._record_answer_quality(
                last_candidate_turn,
                is_intro_reply=not self.candidate_turns,
                answer_eval=answer_eval,
                update_counters=False,
            )
        finally:
            self.last_question_intent = previous_intent
            self.last_question_competency_id = previous_competency
        if answer_eval.needs_clarification:
            # A real-but-ambiguous answer forces CLARIFY_CURRENT_ANSWER on the next
            # turn, via the same consecutive_unusable counter the policy engine
            # already uses for silence/gibberish.
            self.consecutive_unusable += 1
            logger.info(
                "answer_needs_clarification",
                extra={
                    "event": "answer_needs_clarification",
                    "consecutive_unusable": self.consecutive_unusable,
                },
            )

    def _remember_generated(self, generated: GeneratedQuestion, policy: PolicyDecision | None) -> None:
        if policy and policy.intent == "consistency_check":
            self.contradiction_pending = False
        if policy and policy.intent == "final_addition":
            self.final_addition_offered = True
        self.last_question_competency_id = generated.competency_id or (
            policy.competency_id if policy else None
        )
        self.last_question_intent = generated.intent or (policy.intent if policy else "live_question")
        self.last_question_depth = generated.depth
        self.last_question_claim_ids = list(generated.source_claim_ids)
        if self.last_question_competency_id and generated.probe_shape:
            self.last_probe_shape[self.last_question_competency_id] = generated.probe_shape
        mark_intent_asked(
            self.coverage,
            competency_id=self.last_question_competency_id,
            intent=self.last_question_intent,
        )

    def _capture_replay(self, raw: str, *, validator_ok: bool | None, reasons: list[str] | None = None) -> None:
        self.last_raw_model_output = (raw or "")[:2000] or None
        self.last_validator_ok = validator_ok
        self.last_validator_reasons = list(reasons or [])

    def _job_target_level(self) -> str:
        return str(self.candidate_profile.get("job_target_level") or "mid")

    def _role_title(self) -> str:
        if isinstance(self.interview_definition, dict):
            intelligence = self.interview_definition.get("job_intelligence")
            if isinstance(intelligence, dict):
                role = intelligence.get("role") or {}
                if isinstance(role, dict):
                    title = str(role.get("title") or "").strip()
                    if title:
                        return title
        return ""


    def _ensure_opening_cites_context(self, question: str) -> str:
        """Keep LLM wording; soft-weave only a real resume claim (never JD titles).

        Soft-weaving competency / JD labels produced awkward openings like
        "I noticed Service ownership on your materials". Claim-only cites keep
        the greeting human without inventing assessment jargon.
        """
        cleaned = (question or "").strip()
        if not cleaned:
            return self._fallback_opening()
        signal = self._opening_claim_signal()
        if not signal:
            return cleaned
        if self._opening_cites_context(cleaned, signal=signal):
            return cleaned
        logger.info(
            "opening_soft_weave_signal",
            extra={
                "event": "opening_soft_weave_signal",
                "signal": signal[:80],
            },
        )
        return self._weave_opening_signal(cleaned, signal)

    def _opening_cites_context(self, question: str, signal: str | None = None) -> bool:
        """True when spoken opening mentions the chosen claim signal (PBI-B1)."""
        signal = signal if signal is not None else self._opening_claim_signal()
        if not signal:
            return True
        text = (question or "").lower()
        stop = {
            "with", "from", "that", "this", "have", "been", "your", "their",
            "owned", "built", "using", "into", "about", "work", "project",
        }
        tokens = [
            tok
            for tok in re.findall(r"[a-z0-9][a-z0-9+.#-]{3,}", signal.lower())
            if tok not in stop
        ]
        if not tokens:
            needle = signal.lower()[:24].strip()
            return bool(needle) and needle in text
        return any(tok in text for tok in tokens[:8])

    def _weave_opening_signal(self, question: str, signal: str) -> str:
        """Append a short resume cite without discarding the model's greeting."""
        cite = f"I saw you noted {signal}"
        text = question.strip()
        if signal.lower() in text.lower():
            return text
        lower = text.lower()
        for marker in (
            "please introduce",
            "introduce yourself",
            "tell me a bit about yourself",
            "could you introduce",
            "can you introduce",
        ):
            index = lower.find(marker)
            if index > 0:
                before = text[:index].rstrip(" ,;—-")
                after = text[index:]
                joiner = ". " if before and not before.endswith((".", "!", "?")) else " "
                return f"{before}{joiner}{cite} — {after[0].lower() + after[1:] if after else after}"
        match = re.search(r"[.!?]", text)
        if match and match.end() < len(text):
            head = text[: match.end()].rstrip()
            tail = text[match.end() :].lstrip()
            return f"{head} {cite}. {tail}"
        return f"{text.rstrip('.!?')}. {cite}."

    def _opening_claim_signal(self) -> str:
        """Resume claim only — never competency / JD requirement labels."""
        claims = (
            self.candidate_profile.get("claims")
            if isinstance(self.candidate_profile, dict)
            else None
        )
        if not isinstance(claims, list):
            return ""
        ranked = rank_projects_by_competency_gap(
            [item for item in claims if isinstance(item, dict)],
            competencies=self.competencies,
            job_description=self.job_description,
            coverage=self.coverage if isinstance(getattr(self, "coverage", None), dict) else None,
        )
        for item in ranked:
            value = str(item.get("value") or "").strip()
            if value:
                return value if len(value) <= 120 else value[:117].rstrip() + "..."
        return ""

    def _opening_signal(self) -> str:
        """One concrete resume claim or JD signal for fallback openings (PBI-B1)."""
        claim = self._opening_claim_signal()
        if claim:
            return claim
        for req in (self.jd_requirements or [])[:3]:
            text = str(req).strip()
            if text:
                # Skip labels that look like bare competency titles.
                if len(text.split()) <= 3 and text.lower() in {
                    str(c.get("name") or "").lower()
                    for c in (self.competencies or [])
                    if isinstance(c, dict)
                }:
                    continue
                return text if len(text) <= 120 else text[:117].rstrip() + "..."
        return ""

    def _fallback_opening(self) -> str:
        role = self._role_title()
        signal = self._opening_signal()
        if role and signal:
            return (
                f"Thanks for joining. I'm your interviewer for the {role} conversation. "
                f"I saw you noted {signal} — to get started, please introduce "
                "yourself and share the work most relevant to this role."
            )
        if role:
            return (
                f"Thanks for joining. I'm your interviewer for the {role} conversation. "
                "To get started, please introduce yourself — a short overview of your "
                "background, and the work that is most relevant to this role."
            )
        if signal:
            return (
                "Thanks for joining. I'll be interviewing you for this role today. "
                f"I noticed {signal} on your materials — please introduce yourself and "
                "share the work from your background that is most relevant to this job."
            )
        if (self.job_description or "").strip():
            return (
                "Thanks for joining. I'll be interviewing you for this role today. "
                "Please introduce yourself and share the work from your background "
                "that is most relevant to this job."
            )
        return FALLBACK_OPENING

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

    def _priority_guidance(self, competency: dict[str, Any]) -> str:
        current = self.current_phase()
        weight_norm = float(current.get("weight_normalized") or 0.0)
        
        if weight_norm >= 30.0:
            return (
                "CRITICAL PRIMARY COMPETENCY — Demand deep algorithmic logic, step-by-step mechanisms, "
                "time/space complexity, and optimization reasoning. Do not ask behavioral questions or "
                "generic 'what was challenging' questions. Probe for deep technical depth."
            )

        importance = str(competency.get("importance") or "high").strip().lower()
        if importance == "high" or weight_norm >= 15.0:
            return (
                "must-have — use rigorous, detail-seeking phrasing and press for concrete specifics."
            )
        return "preferred — keep it lighter and conversational, but still job-related."

    def _claim_guidance(self) -> str:
        claims = (
            self.candidate_profile.get("claims") if isinstance(self.candidate_profile, dict) else None
        )
        if not claims:
            return (
                "No resume claim is available for this competency. Ask an exploratory "
                "question first rather than assuming or fabricating one."
            )
        return (
            "When a relevant resume claim is listed above, reference its actual project, "
            "tool, or number — never just the competency name."
        )

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
        ledger_entry = self.evidence_ledger.get(competency_id or "")
        target_slot, slot_instruction = target_slot_brief(ledger_entry)
        self._last_target_sent = target_slot
        phase = self.current_phase()
        project_name = str(phase.get("project_name") or "").strip()
        if project_name:
            # Resume walkthrough: the project is the topic, not a JD competency.
            competency = {
                "name": project_name,
                "definition": (
                    "The candidate's own project from their resume. Establish what it "
                    "actually was, what they personally built, and how it works."
                ),
            }
            target_slot, slot_instruction = "", (
                f"Walk through '{project_name}' from the candidate's resume. Get the real "
                "technical substance: what the system did, what they personally built, "
                "and how their part works. Do not move to job competencies yet."
            )
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
            "priority_guidance": self._priority_guidance(competency),
            "ladder_objective": objective or "Ask one job-related question.",
            "missing_intents": ", ".join(missing) or "(none)",
            "evidence_expected": ", ".join(
                str(item) for item in (competency.get("evidence_expected") or [])[:6]
            )
            or "(use the last answer)",
            "allowed_probes": "; ".join(self._allowed_probes()) or "(STAR probes)",
            "evidence_ledger": ledger_brief(ledger_entry)
            if not project_name
            else f"Resume excerpt for this project:\n{resume_project_excerpt(self.resume_text, project_name)}",
            "target_slot": target_slot or "(none)",
            "slot_instruction": slot_instruction,
            "known_facts": self._known_facts_brief(competency_id),
            "hook_fact": self._hook_fact(last_candidate_turn, competency_id, intent)
            or "(none)",
            "required_probe_shape": self._next_probe_shape(competency_id, intent)
            or "(none)",
            "last_probe_shape": self._probe_shape_guidance(competency_id),
            "action_phrasing": action_phrasing_note(decision.action if decision else None),
            "interview_structure": self._interview_structure_text(),
            "published_context": self._published_context_text(competency_id),
            "job_target_level": self._job_target_level(),
            "candidate_framing": self._profile_type(),
            "claim_brief": claim_brief(self.candidate_profile, limit=6),
            "claim_guidance": self._claim_guidance(),
            "jd_excerpt": clip_source_text(self.job_description, 800),
            "recent_turns": "\n".join(f"- {turn}" for turn in self.candidate_turns[-3:])
            or "(none yet)",
            "recent_questions": "\n".join(f"- {q}" for q in self.interviewer_turns[-3:])
            or "(none yet)",
            "last_turn": last_candidate_turn or "(interview opening)",
            "answer_quality": self.last_answer_quality,
            "answer_adaptation": self._answer_adaptation_hint(),
            "previous_evaluation": self._previous_evaluation_brief(),
            "framing_notes": framing_notes(self._profile_type(), self._job_target_level()),
            "language_note": self._language_note(),
            "role_title": str(role.get("title") or ""),
            "reprobe_guidance": self._reprobe_guidance(
                competency_id=competency_id,
                intent=intent,
                last_candidate_turn=last_candidate_turn,
            ),
        }
        system = prompt_pack(self._prompt_version())
        if last_candidate_turn:
            return system + "\n\n" + TURN_INSTRUCTIONS_V2.format_map(briefing), last_candidate_turn
        return system + "\n\n" + OPENING_INSTRUCTIONS_V2.format_map(briefing), (
            "Open the interview in your own words and invite them to introduce themselves."
        )

    def _language_note(self) -> str:
        if self.language.strip().lower() in {"english", "en", ""}:
            return "Speak English."
        return (
            f"Speak {self.language}. Ask every question in {self.language}, but keep "
            "technical terms, tool names and code identifiers in their original form."
        )

    def _answer_adaptation_hint(self) -> str:
        if self.last_answer_quality in {"off_topic", "unsupported"}:
            return "stay in the same competency, acknowledge briefly, and ask an easier adjacent question"
        if self.last_answer_quality in {"unclear", "partial"}:
            return "ask for the specific missing evidence before changing topic"
        if self.last_answer_quality == "sufficient":
            return "increase depth by at most one level or move to the next uncovered topic"
        return "continue with the policy-required intent"

    def _previous_evaluation_brief(self) -> str:
        evaluation = self.last_answer_evaluation
        if not isinstance(evaluation, dict) or not evaluation:
            return "(none)"
        substance = str(evaluation.get("technical_substance") or "unknown")
        facts = [
            str(item).strip()
            for item in (evaluation.get("key_facts_stated") or [])
            if str(item).strip()
        ]
        fact_text = ", ".join(facts[:4]) if facts else "no facts stored"
        correct = evaluation.get("factually_correct", True)
        return (
            f"substance={substance}; factually_correct={correct}; "
            f"facts={fact_text}"
        )

    def _interview_structure_text(self) -> str:
        names = [
            str(phase.get("name") or "section").strip()
            for phase in self.phases
            if str(phase.get("name") or "").strip()
        ]
        return " → ".join(names) if names else "(structure unavailable)"

    def _published_context_text(self, competency_id: str | None = None) -> str:
        definition = self.interview_definition
        if not isinstance(definition, dict):
            return "(published definition unavailable)"

        def values(items: Any, limit: int = 4) -> str:
            result: list[str] = []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                else:
                    text = str(item).strip()
                if text:
                    result.append(text[:100])
            return "; ".join(result[:limit]) or "(none)"

        intelligence = definition.get("job_intelligence")
        role = intelligence.get("role") if isinstance(intelligence, dict) else {}
        competency = competency_by_id(definition, competency_id)
        # Active competency first so the published-context cap never truncates the ask.
        # Claims and raw JD are supplied separately in the turn template — do not
        # duplicate them here (that was blowing TURN_PROMPT_BUDGET_CHARS).
        lines = [
            "ACTIVE CONTEXT (policy remains authoritative):",
            f"Role: {role.get('title', '')} | Level: {role.get('target_level', '')}",
        ]
        if competency:
            lines.append(
                f"Competency: {competency.get('name') or competency_id}: "
                f"{str(competency.get('definition') or '')[:240]}"
            )
            evidence = ", ".join(
                str(item) for item in (competency.get("evidence_expected") or [])[:6]
            )
            if evidence:
                lines.append(f"Evidence needed: {evidence}")
            for step in ladder_steps(definition, competency_id):
                if str(step.get("intent") or "") == (
                    self.last_policy_decision.intent if self.last_policy_decision else ""
                ):
                    objective = str(step.get("objective") or "").strip()
                    if objective:
                        lines.append(f"Current objective: {objective[:180]}")
                    break
        if isinstance(intelligence, dict):
            mandatory = values(intelligence.get("mandatory_requirements"), 4)
            responsibilities = values(intelligence.get("responsibilities"), 3)
            tools = values(intelligence.get("tools"), 4)
            skills = values(intelligence.get("skills"), 4)
            if mandatory != "(none)":
                lines.append(f"Mandatory: {mandatory}")
            if responsibilities != "(none)":
                lines.append(f"Responsibilities: {responsibilities}")
            if tools != "(none)":
                lines.append(f"Tools: {tools}")
            if skills != "(none)":
                lines.append(f"Skills: {skills}")
        return "\n".join(lines)[:PUBLISHED_CONTEXT_LIMIT_CHARS]

    def _fallback_spoken_question(
        self,
        policy: PolicyDecision | None,
        last_turn: str | None = None,
    ) -> str:
        intent = policy.intent if policy else "opening"
        competency_id = policy.competency_id if policy else None
        if self._uses_legacy_decision_flow():
            return FALLBACK_FOLLOWUP
        configured = self._configured_ladder_question(policy)
        spoken = configured or ladder_fallback_question(
            self.interview_definition,
            competency_id=competency_id,
            intent=intent,
        )
        # Do not glue candidate words into stock lines ("You mentioned X").
        # Spoken fallbacks must stay job/ladder-based; the LLM owns natural phrasing.
        return spoken

    _REPAIR_HINTS = {
        "duplicate_question": "that question repeats one already asked — ask about a different, unexplored angle",
        "compound_question": "ask exactly one question, not two",
        "leading_question": "do not put the answer inside the question",
        "protected_topic": "remove the protected-class reference",
        "competency_mismatch": "stay on the competency the policy engine selected",
        "unknown_intent": "use the intent the policy engine supplied",
        "depth_exceeded": "stay within the allowed depth",
        "depth_jump": "advance depth by at most one level",
        "unknown_claim_id": "only cite resume claim ids that were supplied",
        "empty_question": "the question field was empty",
    }

    def _repair_instruction(self, reasons: list[str]) -> str:
        notes = [self._REPAIR_HINTS[r] for r in reasons if r in self._REPAIR_HINTS]
        if not notes:
            return ""
        return (
            "\n\nYour previous question was rejected. Rewrite it: "
            + "; ".join(notes)
            + ". Return the same JSON shape."
        )

    def _precheck_spoken_question(
        self, question: str, policy: PolicyDecision | None
    ) -> bool:
        """Validate a streamed question before any of it reaches TTS.

        Once audio starts there is no way to retract it, so the duplicate,
        compound, leading and protected-topic rules have to run here rather than
        after the turn completes.
        """
        text = (question or "").strip()
        if not text:
            return False
        candidate = GeneratedQuestion(
            question=text,
            competency_id=policy.competency_id if policy else None,
            intent=policy.intent if policy else "live_question",
            depth=policy.current_depth if policy else 1,
        )
        result = validate_generated_question(
            candidate,
            definition=self.interview_definition,
            policy_competency_id=policy.competency_id if policy else None,
            policy_intent=policy.intent if policy else candidate.intent,
            policy_depth=policy.current_depth if policy else candidate.depth,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:],
        )
        if not result.ok:
            logger.info(
                "question_blocked_before_speech",
                extra={
                    "event": "question_blocked_before_speech",
                    "reasons": result.reasons,
                    "prompt_version": self._prompt_version(),
                },
            )
        # Strict here on purpose: blocking buys a repair retry. The relaxed rule
        # lives in _coerce_generated, which decides what to say once the model
        # has had that second attempt.
        return result.ok

    def _coerce_generated(
        self,
        raw: str,
        *,
        policy: PolicyDecision | None,
        last_candidate_turn: str | None,
        use_fallback: bool = True,
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
        policy_intent = policy.intent if policy else parsed.intent
        competency_id = policy.competency_id if policy else None
        hook_fact = self._hook_fact(last_candidate_turn, competency_id, policy_intent)
        self.last_hook_fact = hook_fact
        required_shape = self._next_probe_shape(competency_id, policy_intent)
        result = validate_generated_question(
            parsed,
            definition=self.interview_definition,
            policy_competency_id=competency_id,
            policy_intent=policy_intent,
            policy_depth=policy.current_depth if policy else parsed.depth,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
            hook_fact=hook_fact,
            required_probe_shape=required_shape or None,
            last_probe_shape=self.last_probe_shape.get(competency_id or "") or None,
        )
        self._capture_replay(raw, validator_ok=result.ok, reasons=result.reasons)
        if result.ok:
            return result.question
        logger.info(
            "question_validation_failed",
            extra={
                "event": "question_validation_failed",
                "reasons": result.reasons,
                "speakable": is_speakable(result.reasons),
                "prompt_version": self._prompt_version(),
            },
        )
        if not use_fallback:
            # Keep rejected text available for a rewrite attempt.
            return GeneratedQuestion(
                question=(parsed.question or "").strip(),
                competency_id=competency_id,
                intent=policy_intent or "live_question",
                depth=policy.current_depth if policy else parsed.depth,
                answer_evaluation=parsed.answer_evaluation,
                probe_shape=parsed.probe_shape,
                depth_tag=parsed.depth_tag,
                source_claim_ids=list(parsed.source_claim_ids),
                decision=parsed.decision,
            )
        fallback = self._fallback_spoken_question(policy, last_turn=last_candidate_turn)
        fallback_parsed = GeneratedQuestion(
            question=fallback,
            competency_id=policy.competency_id if policy else None,
            intent=policy.intent if policy else "live_question",
            depth=policy.current_depth if policy else 1,
            answer_evaluation=parsed.answer_evaluation,
        )
        # Gate: never ship an unvalidated fallback. Re-check without requiring a
        # candidate-word hook — stock/ladder lines must not echo STT fragments.
        fallback_result = validate_generated_question(
            fallback_parsed,
            definition=self.interview_definition,
            policy_competency_id=competency_id,
            policy_intent=policy_intent,
            policy_depth=policy.current_depth if policy else 1,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
            hook_fact="",
            required_probe_shape=None,
            last_probe_shape=None,
        )
        if fallback_result.ok:
            self._capture_replay(
                fallback, validator_ok=True, reasons=[]
            )
            return fallback_result.question
        # Last resort: build a minimal question, then actually re-validate it.
        # Never mark ok:True without a real pass (sales turn-6 greenwash bug).
        safe = self._safe_gated_question(
            policy, last_turn=last_candidate_turn, hook_fact=hook_fact
        )
        safe_parsed = GeneratedQuestion(
            question=safe,
            competency_id=competency_id,
            intent=policy_intent or "live_question",
            depth=policy.current_depth if policy else 1,
            answer_evaluation=parsed.answer_evaluation,
        )
        safe_result = validate_generated_question(
            safe_parsed,
            definition=self.interview_definition,
            policy_competency_id=competency_id,
            policy_intent=policy_intent,
            policy_depth=policy.current_depth if policy else 1,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
            hook_fact="",
            required_probe_shape=None,
            last_probe_shape=None,
        )
        if safe_result.ok:
            self._capture_replay(
                safe, validator_ok=True, reasons=["safe_gated_fallback"]
            )
            return safe_result.question
        # Still invalid (e.g. compound default / bad hook): ship a bland single
        # ask that is known-clean rather than a known-bad dual ask. Prefer UX
        # safety over shipping a broken question with an honest ok:False.
        clean = self._ultimate_clean_question(hook_fact)
        clean_parsed = GeneratedQuestion(
            question=clean,
            competency_id=competency_id,
            intent=policy_intent or "live_question",
            depth=policy.current_depth if policy else 1,
            answer_evaluation=parsed.answer_evaluation,
        )
        clean_result = validate_generated_question(
            clean_parsed,
            definition=self.interview_definition,
            policy_competency_id=competency_id,
            policy_intent=policy_intent,
            policy_depth=policy.current_depth if policy else 1,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
            hook_fact=hook_fact if (hook_fact or "").strip().lower() in clean.lower() else "",
            required_probe_shape=None,
            last_probe_shape=None,
        )
        if clean_result.ok:
            self._capture_replay(
                clean,
                validator_ok=True,
                reasons=["safe_gated_fallback", "ultimate_clean_fallback"],
            )
            return clean_result.question
        # Absolute last resort: ship the bland line with honest ok:False so
        # harness / logs never claim a clean pass that was not checked.
        self._capture_replay(
            clean,
            validator_ok=False,
            reasons=list(clean_result.reasons) + ["ultimate_clean_unvalidated"],
        )
        return clean_parsed

    def _ultimate_clean_question(self, hook_fact: str) -> str:
        """Guaranteed single-ask bland prompt — preferred over shipping known-bad.

        Never echo candidate STT fragments ("Regarding thank you…"). The LLM
        should phrase hooks; this path only keeps the conversation alive.
        """
        _ = hook_fact  # retained for call-site compatibility
        return "Can you tell me more about that?"

    def _capture_spoken_validation(
        self,
        spoken: str,
        *,
        policy: PolicyDecision | None,
        last_candidate_turn: str | None,
    ) -> None:
        """Post-hoc validate already-spoken audio; never invent ok:True."""
        policy_intent = policy.intent if policy else "live_question"
        competency_id = policy.competency_id if policy else None
        hook_fact = self._hook_fact(last_candidate_turn, competency_id, policy_intent)
        parsed = GeneratedQuestion(
            question=(spoken or "").strip(),
            competency_id=competency_id,
            intent=policy_intent,
            depth=policy.current_depth if policy else 1,
        )
        result = validate_generated_question(
            parsed,
            definition=self.interview_definition,
            policy_competency_id=competency_id,
            policy_intent=policy_intent,
            policy_depth=policy.current_depth if policy else 1,
            max_depth=policy.max_depth if policy else 5,
            recent_questions=self.interviewer_turns[-8:],
            allowed_probes=self._allowed_probes(),
            profile=self.candidate_profile,
            job_description=self.job_description,
            resume_text=self.resume_text,
            recent_turns=self.candidate_turns[-4:]
            + ([last_candidate_turn] if last_candidate_turn else []),
            hook_fact=hook_fact,
        )
        reasons = list(result.reasons)
        if "shipped_pre_validation" not in reasons:
            reasons.append("shipped_pre_validation")
        self._capture_replay(
            spoken, validator_ok=result.ok, reasons=reasons
        )

    def _safe_gated_question(
        self,
        policy: PolicyDecision | None,
        *,
        last_turn: str | None,
        hook_fact: str,
    ) -> str:
        """Last-resort spoken question that includes the hook stem when required."""
        intent = policy.intent if policy else "live_question"
        competency_id = policy.competency_id if policy else None
        base = ladder_fallback_question(
            self.interview_definition,
            competency_id=competency_id,
            intent=intent,
        )
        # Ladder / intent defaults only — never "Regarding {candidate words}".
        _ = hook_fact
        return base or "Can you share one concrete example from that work?"

    def _uses_legacy_decision_flow(self) -> bool:
        return (not self.policy_mode) and self.allow_legacy_flow

    def _prompt_for_turn(
        self, last_candidate_turn: str | None
    ) -> tuple[str, str]:
        if not self._uses_legacy_decision_flow():
            return self._structured_system_prompt(
                last_candidate_turn,
                self._current_policy_decision(
                    pending_candidate_turn=bool(last_candidate_turn),
                    advance_if_ready=True,
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
        if last_candidate_turn is None:
            # Legacy path: skip LLM only when there is nothing to personalize from.
            has_opening_context = bool(
                (self.job_description or "").strip()
                or (self.resume_text or "").strip()
                or (
                    isinstance(self.candidate_profile, dict)
                    and (self.candidate_profile.get("claims") or [])
                )
            )
            if self._uses_legacy_decision_flow() and not has_opening_context:
                started = time.perf_counter()
                opening = self._fallback_opening()
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
        if last_candidate_turn and not self._uses_legacy_decision_flow():
            is_intro_reply = not self.candidate_turns
            self._record_answer_quality(
                last_candidate_turn, is_intro_reply=is_intro_reply
            )
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
                self._fallback_opening()
                if last_candidate_turn is None
                else self._fallback_spoken_question(
                    policy, last_turn=last_candidate_turn
                )
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
        return await self._complete_generated_turn(
            raw,
            last_candidate_turn,
            started=started,
            prompt=prompt,
            user_content=user_content,
        )

    async def _complete_generated_turn(
        self,
        raw: str,
        last_candidate_turn: str | None,
        *,
        started: float,
        prompt: str,
        user_content: str,
        allow_retry: bool = True,
        spoken_question: str | None = None,
        spoken_any: bool = False,
    ) -> str:
        policy = self.last_policy_decision
        if not self._uses_legacy_decision_flow():
            generated = self._coerce_generated(
                raw,
                policy=policy,
                last_candidate_turn=last_candidate_turn,
                use_fallback=False,
            )
            parsed = parse_generated_question(raw)
            needs_rewrite = self.last_validator_ok is False or (
                allow_retry
                and parsed is None
                and not (generated.question or "").strip()
            )
            if allow_retry and needs_rewrite and not spoken_any:
                reasons = ", ".join(self.last_validator_reasons) or "invalid_question"
                rejected = (generated.question or "").strip() or "(empty)"
                rewrite_user = (
                    f"{user_content}\n\n"
                    f"REWRITE REQUIRED. Previous question was rejected ({reasons}). "
                    f"Rejected text: {rejected!r}. "
                    "Write ONE better question for the same competency and intent. "
                    "Do not lead the candidate, do not ask two questions, "
                    "and do not use a template filler."
                )
                try:
                    raw = await self.llm_client.generate_reply(
                        [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": rewrite_user},
                        ]
                    )
                    logger.info(
                        "question_rewrite_attempt",
                        extra={
                            "event": "question_rewrite_attempt",
                            "reasons": self.last_validator_reasons,
                        },
                    )
                    generated = self._coerce_generated(
                        raw,
                        policy=policy,
                        last_candidate_turn=last_candidate_turn,
                        use_fallback=True,
                    )
                    if self.last_validator_ok:
                        generated = retried
                except Exception:
                    logger.exception(
                        "stage2_question_retry_failed",
                        extra={"event": "stage2_question_retry_failed"},
                    )
                    generated = self._coerce_generated(
                        "",
                        policy=policy,
                        last_candidate_turn=last_candidate_turn,
                        use_fallback=True,
                    )
            elif self.last_validator_ok is False:
                generated = self._coerce_generated(
                    raw,
                    policy=policy,
                    last_candidate_turn=last_candidate_turn,
                    use_fallback=True,
                )
            if spoken_any and spoken_question:
                # Voice already committed audio — cannot retract. Keep spoken text
                # but re-validate honestly so ok/reasons match what the candidate heard.
                generated.question = spoken_question
                self._capture_spoken_validation(
                    spoken_question,
                    policy=policy,
                    last_candidate_turn=last_candidate_turn,
                )
            decision, question = generated.decision, generated.question
            # Credit coverage against the question that was just answered, not the
            # newly generated follow-up intent we are about to remember.
            asked_intent = self.last_question_intent
            asked_competency = self.last_question_competency_id
            self._remember_generated(generated, policy)
            self._refine_answer_quality(
                last_candidate_turn,
                generated,
                asked_intent=asked_intent,
                asked_competency_id=asked_competency,
            )
        else:
            decision, question = parse_stage2(raw)
            if spoken_any and spoken_question:
                question = spoken_question
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
        if last_candidate_turn is None:
            question = self._ensure_opening_cites_context(question)
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
                "prompt_chars": len(prompt),
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
        if not self._uses_legacy_decision_flow():
            async for chunk in self._stream_policy_question(last_candidate_turn):
                yield chunk
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
            question = self._fallback_opening() if is_opening else FALLBACK_FOLLOWUP
            yield question
        elif is_opening:
            ensured = self._ensure_opening_cites_context(question)
            if ensured != question:
                question = ensured
                yield question
        self._commit_turn(
            last_candidate_turn,
            parser.decision or "probe",
            started=started,
            is_opening=is_opening,
            question=question,
        )

    async def _stream_policy_question(self, last_candidate_turn: str | None):
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
        if last_candidate_turn:
            is_intro_reply = not self.candidate_turns
            self._record_answer_quality(
                last_candidate_turn, is_intro_reply=is_intro_reply
            )
        prompt, user_content = self._prompt_for_turn(last_candidate_turn)
        started = time.perf_counter()
        policy = self.last_policy_decision
        attempt: dict[str, Any] = {}

        async def _pump_stream():
            parser = SpokenJsonQuestionStream()
            raw_parts: list[str] = []
            spoken_any = False
            failed = False
            try:
                async for delta in stream(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ]
                ):
                    raw_parts.append(delta or "")
                    spoken = parser.push(delta or "")
                    if spoken:
                        spoken_any = True
                        yield spoken
            except Exception:
                logger.exception(
                    "stage2_question_failed",
                    extra={"event": "stage2_question_failed"},
                )
                failed = True
            leftover = parser.finish()
            if leftover:
                spoken_any = True
                yield leftover
            attempt["parser"] = parser
            attempt["raw_parts"] = raw_parts
            attempt["spoken_any"] = spoken_any
            attempt["failed"] = failed

        spoken_any = False
        async for chunk in _pump_stream():
            spoken_any = True
            yield chunk
        if not spoken_any and not attempt.get("failed"):
            logger.warning(
                "stage2_empty_stream_retry",
                extra={"event": "stage2_empty_stream_retry"},
            )
            async for chunk in _pump_stream():
                spoken_any = True
                yield chunk

        parser = attempt.get("parser") or SpokenJsonQuestionStream()
        raw_parts = list(attempt.get("raw_parts") or [])
        failed = bool(attempt.get("failed"))

        if failed:
            fallback = (
                self._fallback_opening()
                if last_candidate_turn is None
                else self._fallback_spoken_question(
                    policy, last_turn=last_candidate_turn
                )
            )
            if self.completed:
                fallback = CLOSING_MESSAGE
            if last_candidate_turn:
                is_intro_reply = not self.candidate_turns
                self.candidate_turns.append(last_candidate_turn)
                self._apply_turn_decision(
                    self._normalize_decision("probe", is_intro_reply=is_intro_reply),
                    is_intro_reply=is_intro_reply,
                )
            question = parser.question.strip() or fallback
            generated = GeneratedQuestion(
                question=question,
                competency_id=policy.competency_id if policy else None,
                intent=policy.intent if policy else "live_question",
                depth=policy.current_depth if policy else 1,
            )
            self._remember_generated(generated, policy)
            self._remember_question(question)
            if not spoken_any:
                yield question
            return
        # finish() already ran inside _pump_stream; reuse the spoken question text.
        spoken = parser.question.strip() or None
        question = await self._complete_generated_turn(
            "".join(raw_parts),
            last_candidate_turn,
            started=started,
            prompt=prompt,
            user_content=user_content,
            allow_retry=not spoken_any,
            spoken_question=spoken,
            spoken_any=spoken_any,
        )
        if question == CLOSING_MESSAGE:
            if (spoken or "") != CLOSING_MESSAGE:
                yield question
            return
        if last_candidate_turn is None and spoken_any and question != (spoken or ""):
            # Soft-replaced opening after stream — speak corrected claim-aware line once.
            yield question
            return
        if not spoken_any and question:
            yield question
