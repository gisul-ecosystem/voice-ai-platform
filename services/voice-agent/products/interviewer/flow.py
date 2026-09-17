"""Provider-neutral interview question flow."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Protocol

logger = logging.getLogger("voice-agent.aaptor")

MAX_PROBES_PER_PHASE = int(os.getenv("MAX_PROBES_PER_PHASE", "8"))
FALLBACK_OPENING = (
    "Thanks for joining. I'm your interviewer for this conversation. "
    "To get started, please introduce yourself — a short overview of your "
    "background, and the work that is most relevant to this role."
)
CLOSING_MESSAGE = (
    "Thank you for your time and for sharing your experience. "
    "This concludes the interview."
)
FALLBACK_FOLLOWUP = (
    "Thank you. On that same piece of work, what was the main API or data store "
    "you owned, and what happened when it failed?"
)

STAGE2_SYSTEM = """You are Aaptor, a senior technical interviewer speaking live. Sound like a calm, clear human in the room. Speak slowly: one idea at a time, short sentences, easy for anyone who uses Indian English at work.

CURRENT INTENT: {intent}
FOCUS NOW: {focus_item}
You must ask a question that matches this intent and this focus. Do not jump ahead in the agenda.

AGENDA (fixed order):
{agenda}

Interview length: about {target_minutes} minutes. Elapsed: {elapsed_minutes} min. Remaining: {remaining_minutes} min.
Current thread: {phase_name} (guide {duration_minutes} min, {phase_elapsed_minutes} used). Topics: {topics}
Follow-ups here: {probe_count}
Later (only after every resume project has had a technical question, unless time is almost gone): {next_phase}

{resume_brief}

Job description:
{jd_excerpt}

Role competencies: {competencies}
Job requirements still missing a question: {uncovered_requirements}
Job requirements already touched: {covered_requirements}

Projects still missing a technical question: {uncovered_projects}
Projects already touched: {covered_projects}

Recent candidate turns (their knowledge in this interview):
{recent_turns}

Questions you already asked — do not copy the wording, the stem, or the pattern:
{recent_questions}

Last answer — stay in this context:
{last_turn}

Think, then choose PROBE or ADVANCE.
{phase_pacing}
- Deep-dive slowly. Stay on the same answer. Ask the next layer: first what they built, then how it worked, then one technical detail (API, schema, queue, lock, index, timeout, retry), then a failure or tradeoff. Do not jump to a new project until that thread has a real technical example.
- If INTENT is resume_project: the question must be about FOCUS NOW, using their last answer and the resume. ADVANCE means the next uncovered resume project, not DSA or role-fit.
- If INTENT is jd_requirement: the question must check FOCUS NOW from the job (for example DSA if that is the focus). Ground it in their resume or last answer when you can, but still ask the requirement.
- Use proper technical terms, but always attach context from their words.
- Prefer PROBE. ADVANCE only after two or three connected technical follow-ups, unless time is almost gone.
- Never repeat an asking style (no looping walk-me-through / challenges / tell-me-more).
- You must still reach every listed resume project, then remaining job requirements. If time is short, one clear technical question per remaining item.
- Do not invent employers, projects, or skills. Anti-bias: no age, family, nationality, or health.

Speak 1-2 short sentences: a brief reaction, then one original question. Simple English. No markdown, lists, or quotation marks. Never say phase, outline, probe, or advance.

Output format (strict):
Line 1: DECISION: probe
or
Line 1: DECISION: advance
Then a blank line, then the spoken words only.
"""

INTRO_FOLLOWUP_SYSTEM = """You are Aaptor, a senior technical interviewer. Speak slowly and clearly. The candidate just introduced themselves.

CURRENT INTENT: intro
FOCUS NOW: {focus_item}
After the introduction, start the first resume project. Do not ask DSA, system design, or role-fit yet.

{resume_brief}

Job description:
{jd_excerpt}

Role competencies: {competencies}

Projects you must eventually cover: {uncovered_projects}
First project to open: {focus_item}

Their introduction:
{last_turn}

- Always DECISION: probe.
- Pick the project they named in the intro if it is on the resume; otherwise use FOCUS NOW.
- Ask one technical question in that project's context — for example the API, data store, or their ownership.
- Use a technical term and explain it in the same sentence with their context.
- 1-2 short spoken sentences. No markdown, lists, or quotation marks. Never say phase, outline, probe, or advance.
- Do not invent employers, projects, or skills. Anti-bias: no age, family, nationality, or health.

Output format (strict):
Line 1: DECISION: probe

Then a blank line, then the spoken words only.
"""

OPENING_SYSTEM = """You are Aaptor, a live technical interviewer. Speak slowly and clearly, in simple English. Write a fresh opening. Do not use a memorized script.

{resume_brief}

Job description:
{jd_excerpt}

Role competencies: {competencies}
First thread (guide only): {phase_name}. Topics: {topics}

Greet them, say you are the interviewer, and invite a short introduction. If the resume names projects, you may say you looked over their work and will go through those projects one by one, in some technical depth — without starting the grilling yet.

2-3 short spoken sentences. Warm and easy to follow. No markdown, lists, or quotation marks. Do not mention phases, outlines, or probes. Do not invent projects. Anti-bias: no identity or accent comments.

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
    return found[:12]


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
    ) -> None:
        self.outline = outline
        self.llm_client = llm_client
        self.max_probes_per_phase = max_probes_per_phase
        self.phases: list[dict] = list(outline.get("phases") or [])
        self.phase_index = max(0, min(initial_phase_index, max(len(self.phases) - 1, 0)))
        self.probe_count = max(0, initial_probe_count)
        self.candidate_turns = list(candidate_turns or [])
        self.interviewer_turns = list(interviewer_turns or [])
        self.job_description = job_description
        self.resume_text = resume_text
        self.competencies = list(competencies or [])
        self.resume_projects = extract_resume_projects(resume_text)
        self.jd_requirements = extract_jd_requirements(
            job_description, self.competencies
        )
        self.focus_item = ""
        self._touched_topics: set[str] = set()
        self.completed = False
        self.started_at = time.monotonic()
        self.phase_started_at = self.started_at
        phase_minutes = sum(
            max(int(phase.get("duration_minutes", 0)), 0) for phase in self.phases
        )
        self.target_duration_minutes = max(
            1,
            int(
                target_duration_minutes
                if target_duration_minutes is not None
                else (phase_minutes or 30)
            ),
        )
        self.max_duration_seconds = self.target_duration_minutes * 60
        self.min_turns_before_close = (
            min_turns_before_close
            if min_turns_before_close is not None
            else max(12, self.target_duration_minutes // 2)
        )

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
            return
        if self._rotate_focus():
            return
        if at_last:
            self.probe_count += 1
            if self._time_up():
                self.completed = True
                logger.info(
                    "interview_completed",
                    extra={
                        "event": "interview_completed",
                        "phase_index": self.phase_index,
                    },
                )
            return
        next_phase = self.next_phase()
        skip_ahead = False
        if (
            next_phase is not None
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
        flow_limit = max(3, self._phase_minutes() // 2)
        return min(self.max_probes_per_phase, flow_limit)

    def _is_warmup_phase(self) -> bool:
        return self._phase_intent() == "intro"

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

    def _spoken_so_far(self) -> str:
        return " ".join(self.interviewer_turns + self.candidate_turns).lower()

    def _covered_items(self, names: list[str]) -> list[str]:
        spoken = self._spoken_so_far()
        return [
            name
            for name in names
            if _item_mentioned(name, spoken) or name.lower() in self._touched_topics
        ]

    def _uncovered_items(self, names: list[str]) -> list[str]:
        spoken = self._spoken_so_far()
        return [
            name
            for name in names
            if not _item_mentioned(name, spoken)
            and name.lower() not in self._touched_topics
        ]

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
            uncovered = self._uncovered_requirements()
            if self.focus_item in uncovered:
                return
            self.focus_item = (uncovered or self.jd_requirements or ["this job requirement"])[0]
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
                for name in self._uncovered_requirements()
                if name.lower() != (self.focus_item or "").lower()
            ]
            if remaining and self._time_remaining_minutes() > 2:
                self.focus_item = remaining[0]
                self.probe_count = 0
                return True
        return False

    def _agenda_text(self) -> str:
        projects = ", ".join(self.resume_projects) or "(none parsed)"
        requirements = ", ".join(self.jd_requirements) or "(none parsed from JD)"
        return (
            "1. Intro — candidate background.\n"
            f"2. Resume projects, one by one: {projects}\n"
            f"3. Job requirements after projects: {requirements}\n"
            "4. Role fit only if time remains."
        )

    def _time_remaining_minutes(self) -> int:
        return max(0, self.target_duration_minutes - self._elapsed_minutes())

    def _phase_pacing(self) -> str:
        uncovered = ", ".join(self._uncovered_projects()) or "none"
        missing_req = ", ".join(self._uncovered_requirements()) or "none"
        intent = self._phase_intent()
        if intent == "intro":
            return (
                "- Warm-up is a short bridge. After the intro, start a slow "
                f"technical deep-dive on FOCUS NOW. Uncovered projects: {uncovered}."
            )
        if intent == "jd_requirement":
            return (
                "- Projects are done or time is tight. Ask the next uncovered job "
                f"requirement ({missing_req}). If FOCUS NOW is DSA, ask one practical "
                "DSA question tied to their work when possible."
            )
        if intent == "role_fit":
            return (
                "- Only motivation/role-fit now. Do not reopen a finished project "
                "unless they bring it up."
            )
        return (
            "- Stay on this answer and go one layer deeper with a technical term "
            "in context. When you ADVANCE, go to the next uncovered resume "
            f"project ({uncovered}), not generic motivation or DSA yet. "
            f"Job requirements waiting after projects: {missing_req}."
        )

    def _too_early_to_advance(self) -> bool:
        if self._is_warmup_phase():
            return False
        if self._should_leave_phase():
            return False
        remaining = self._time_remaining_minutes()
        uncovered = self._uncovered_projects()
        if uncovered and remaining <= max(4, len(uncovered) * 2):
            return self.probe_count < 1
        return self.probe_count < 3

    def _normalize_decision(self, decision: str, *, is_intro_reply: bool) -> str:
        if is_intro_reply:
            return "probe"
        if self._too_early_to_advance():
            return "probe"
        if self._should_leave_phase():
            return "advance"
        return decision

    def _apply_turn_decision(self, decision: str, *, is_intro_reply: bool) -> None:
        if is_intro_reply:
            self.probe_count += 1
            return
        self.apply_decision(decision)

    def _should_leave_phase(self) -> bool:
        if self._is_warmup_phase():
            return self.probe_count >= 2
        if (
            self._is_project_phase()
            and self._uncovered_projects()
            and self._time_remaining_minutes() > 3
            and self.probe_count < self._phase_probe_limit()
        ):
            return False
        phase_elapsed = time.monotonic() - self.phase_started_at
        return (
            self.probe_count >= self._phase_probe_limit()
            or phase_elapsed >= self._phase_minutes() * 60
        )

    def _time_up(self) -> bool:
        return time.monotonic() - self.started_at >= self.max_duration_seconds

    def _elapsed_minutes(self) -> int:
        return max(0, int((time.monotonic() - self.started_at) / 60))

    def _remember_question(self, question: str) -> None:
        text = (question or "").strip()
        if text and text != CLOSING_MESSAGE:
            self.interviewer_turns.append(text)

    def _ready_to_close(self) -> bool:
        return self._time_up() and len(self.candidate_turns) >= self.min_turns_before_close

    def _closing_speech(self, last_candidate_turn: str | None) -> str | None:
        if self.completed:
            return CLOSING_MESSAGE
        if self._time_up():
            if last_candidate_turn:
                self.candidate_turns.append(last_candidate_turn.strip())
            self.completed = True
            return CLOSING_MESSAGE
        return None

    def _prompt_for_turn(
        self, last_candidate_turn: str | None
    ) -> tuple[str, str]:
        phase = self.current_phase()
        next_phase = self.next_phase()
        next_phase_label = (
            f"{next_phase.get('name')} — topics: {phase_topics(next_phase)}"
            if next_phase
            else "none (closing)"
        )
        recent = self.candidate_turns[-2:]
        recent_questions = self.interviewer_turns[-3:]
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
            "uncovered_requirements": ", ".join(self._uncovered_requirements())
            or "(none left)",
            "covered_requirements": ", ".join(self._covered_requirements())
            or "(none yet)",
        }
        is_intro_reply = bool(last_candidate_turn) and not self.candidate_turns
        self._ensure_focus(last_candidate_turn, is_intro_reply=is_intro_reply)
        if last_candidate_turn:
            if is_intro_reply:
                prompt = INTRO_FOLLOWUP_SYSTEM.format(
                    last_turn=last_candidate_turn,
                    focus_item=self.focus_item or "(first resume project)",
                    **briefing,
                    **coverage,
                )
                return prompt, last_candidate_turn
            prompt = STAGE2_SYSTEM.format(
                intent=self._phase_intent(),
                focus_item=self.focus_item or phase.get("name", "this topic"),
                agenda=self._agenda_text(),
                phase_name=phase.get("name", "unnamed"),
                duration_minutes=phase.get("duration_minutes", 0),
                topics=phase_topics(phase),
                probe_count=self.probe_count,
                next_phase=next_phase_label,
                target_minutes=self.target_duration_minutes,
                elapsed_minutes=self._elapsed_minutes(),
                remaining_minutes=self._time_remaining_minutes(),
                phase_elapsed_minutes=max(
                    0, int((time.monotonic() - self.phase_started_at) / 60)
                ),
                phase_pacing=self._phase_pacing(),
                recent_turns="\n".join(f"- {turn}" for turn in recent)
                or "(none yet)",
                recent_questions="\n".join(f"- {q}" for q in recent_questions)
                or "(none yet)",
                last_turn=last_candidate_turn,
                **briefing,
                **coverage,
            )
            return prompt, last_candidate_turn
        prompt = OPENING_SYSTEM.format(
            phase_name=phase.get("name", "unnamed"),
            topics=phase_topics(phase),
            **briefing,
        )
        return prompt, (
            "Open the interview in your own words and invite them to "
            "introduce themselves."
        )

    async def generate_next_question(self, last_candidate_turn: str | None) -> str:
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        closing = self._closing_speech(last_candidate_turn)
        if closing:
            return closing
        if last_candidate_turn is None:
            started = time.perf_counter()
            self._commit_turn(
                None,
                "probe",
                started=started,
                is_opening=True,
                question=FALLBACK_OPENING,
            )
            return FALLBACK_OPENING
        prompt, user_content = self._prompt_for_turn(last_candidate_turn)

        started = time.perf_counter()
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
                else FALLBACK_FOLLOWUP
            )
            if self.completed:
                fallback = CLOSING_MESSAGE
            self._remember_question(fallback)
            return fallback
        decision, question = parse_stage2(raw)
        if last_candidate_turn:
            is_intro_reply = not self.candidate_turns
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
        last_candidate_turn = (last_candidate_turn or "").strip() or None
        closing = self._closing_speech(last_candidate_turn)
        if closing:
            yield closing
            return

        stream = getattr(self.llm_client, "generate_reply_stream", None) or getattr(
            self.llm_client, "stream_reply", None
        )
        if last_candidate_turn is None:
            started = time.perf_counter()
            yield FALLBACK_OPENING
            self._commit_turn(
                None,
                "probe",
                started=started,
                is_opening=True,
                question=FALLBACK_OPENING,
            )
            return

        if stream is None:
            yield await self.generate_next_question(last_candidate_turn)
            return

        prompt, user_content = self._prompt_for_turn(last_candidate_turn)
        started = time.perf_counter()
        parser = SpokenQuestionStream()
        spoken_parts: list[str] = []
        try:
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
            question = FALLBACK_FOLLOWUP
            yield question
        self._commit_turn(
            last_candidate_turn,
            parser.decision or "probe",
            started=started,
            is_opening=False,
            question=question,
        )
