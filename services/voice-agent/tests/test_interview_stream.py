from __future__ import annotations

import time

import pytest

from clients.llm.openai_compat import openai_sse_content_deltas
from products.interviewer.flow import (
    CLOSING_MESSAGE,
    FALLBACK_OPENING,
    InterviewFlow,
    SpokenQuestionStream,
    extract_jd_requirements,
    extract_resume_projects,
    parse_stage2,
)
from products.interviewer.worker import (
    GENERIC_OUTLINE,
    enrich_outline_with_jd,
    enrich_outline_with_resume,
    normalize_probe_count,
    scale_outline_to_duration,
)


class FakeStreamingLlm:
    def __init__(self, *chunks: str) -> None:
        self.chunks = list(chunks)
        self.messages: list[list[dict]] = []

    async def generate_reply_stream(self, messages: list[dict], **_kwargs):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


def test_probe_count_normalization_honors_recruiter_limits() -> None:
    assert normalize_probe_count(0) == 0
    assert normalize_probe_count("3") == 3
    assert normalize_probe_count(20) == 3
    assert normalize_probe_count(None) == 2


def test_spoken_question_stream_skips_decision_line() -> None:
    parser = SpokenQuestionStream()
    assert parser.push("DECISION: probe") == ""
    assert parser.push("\n\nCould you") == "Could you"
    assert parser.push(" walk me through that?") == " walk me through that?"
    assert parser.decision == "probe"
    assert parser.finish() == ""


def test_spoken_question_stream_falls_back_without_decision() -> None:
    parser = SpokenQuestionStream()
    spoken = parser.push("Just a spoken question?")
    leftover = parser.finish()
    assert spoken + leftover == "Just a spoken question?"
    _, parsed = parse_stage2("Just a spoken question?")
    assert parsed == "Just a spoken question?"


def test_openai_sse_content_deltas() -> None:
    assert openai_sse_content_deltas("data: [DONE]") == []
    assert openai_sse_content_deltas(
        'data: {"choices":[{"delta":{"content":"Hello"}}]}'
    ) == ["Hello"]
    assert openai_sse_content_deltas("event: ping") == []


@pytest.mark.asyncio
async def test_generate_next_question_stream_yields_after_decision() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "What was the result of that launch?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        llm,
        candidate_turns=["I already introduced myself."],
    )
    chunks = [
        chunk
        async for chunk in flow.generate_next_question_stream("I led the rollout.")
    ]
    assert "".join(chunks) == "What was the result of that launch?"
    assert flow.candidate_turns[-1] == "I led the rollout."
    assert flow.probe_count == 1
    assert "RESUME BRIEF" in llm.messages[0][0]["content"]


@pytest.mark.asyncio
async def test_followup_prompt_includes_resume_projects() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "How did you design checkout in the Payments Gateway project?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        llm,
        resume_text=(
            "Projects: Payments Gateway on AWS. Skills: Python, Kafka, PostgreSQL."
        ),
        competencies=["Python", "System design"],
        job_description="Backend engineer for payments services.",
    )
    async for _ in flow.generate_next_question_stream("I led the rollout."):
        pass
    prompt = llm.messages[0][0]["content"]
    assert "Payments Gateway" in prompt
    assert "Python, Kafka" in prompt
    assert "Backend engineer for payments" in prompt


@pytest.mark.asyncio
async def test_stage2_prompt_includes_prior_interviewer_questions() -> None:
    llm = FakeStreamingLlm(
        "DECISION: advance\n\n",
        "Which Python skill from this role did you use most on Payments Gateway?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "experience",
                    "duration_minutes": 5,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        llm,
        candidate_turns=["I led the rollout."],
        interviewer_turns=[
            "Could you walk me through the Payments Gateway project?",
            "What challenges did you face?",
        ],
        resume_text=(
            "Projects: Payments Gateway on AWS with Kafka and PostgreSQL. Skills: Python."
        ),
    )
    async for _ in flow.generate_next_question_stream(
        "I owned checkout and cut latency."
    ):
        pass
    prompt = llm.messages[0][0]["content"]
    assert "walk me through" in prompt
    assert "What challenges did you face?" in prompt
    assert "Do not repeat" in prompt
    assert "about 5 minutes" in prompt
    assert "you mentioned" in prompt.lower()
    assert "Resume facts for the current project" in prompt
    assert "BOTH that last answer and the resume facts" in prompt
    assert "Kafka" in prompt or "PostgreSQL" in prompt
    user = llm.messages[0][1]["content"]
    assert "Latest answer, in full" in user
    assert "I owned checkout and cut latency." in user
    assert "Resume facts" in user


@pytest.mark.asyncio
async def test_opening_stream_asks_for_an_intro() -> None:
    llm = FakeStreamingLlm(
        "Hi — thanks for coming in. I'm Aaptor. Who are you, and what work "
        "from the last couple of years are you most proud of?"
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "warm-up",
                    "duration_minutes": 5,
                    "topics": ["background"],
                    "source": "generic",
                }
            ]
        },
        llm,
        resume_text="Projects\n- Payments Gateway: checkout on AWS",
    )
    chunks = [chunk async for chunk in flow.generate_next_question_stream(None)]
    spoken = "".join(chunks)
    assert "who are you" in spoken.lower()
    assert flow.candidate_turns == []
    assert llm.messages
    assert "Invent a short, warm opening" in llm.messages[0][0]["content"]


@pytest.mark.asyncio
async def test_first_answer_uses_intro_followup_prompt() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "You mentioned payments — what was your role on that project?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "warm-up",
                    "duration_minutes": 5,
                    "topics": ["background"],
                    "source": "generic",
                }
            ]
        },
        llm,
        resume_text="Projects: Payments Gateway. Skills: Python.",
    )
    async for _ in flow.generate_next_question_stream(
        "I am a backend engineer and I built a payments gateway."
    ):
        pass
    prompt = llm.messages[0][0]["content"]
    assert "introduced themselves" in prompt
    assert "Payments Gateway" in prompt
    assert "walk me through" in prompt.lower()
    user = llm.messages[0][1]["content"]
    assert "whole intro" in user.lower()
    assert flow.probe_count == 1


@pytest.mark.asyncio
async def test_stream_closes_when_target_duration_elapsed() -> None:
    llm = FakeStreamingLlm("should not run")
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "technical",
                    "duration_minutes": 10,
                    "topics": ["Python"],
                    "source": "jd",
                }
            ]
        },
        llm,
        target_duration_minutes=30,
    )
    flow.started_at = time.monotonic() - flow.max_duration_seconds - 1
    chunks = [
        chunk
        async for chunk in flow.generate_next_question_stream("Answer three")
    ]
    assert "".join(chunks) == CLOSING_MESSAGE
    assert llm.messages == []
    assert flow.completed is True


def test_phase_probe_limit_follows_phase_minutes() -> None:
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["ownership"],
                    "source": "resume",
                }
            ]
        },
        FakeStreamingLlm(),
        max_probes_per_phase=8,
        target_duration_minutes=30,
    )
    assert flow.target_duration_minutes == 30
    assert flow._phase_probe_limit() == 5
    assert flow.max_duration_seconds == 30 * 60


@pytest.mark.asyncio
async def test_stays_on_phase_instead_of_jumping_early() -> None:
    llm = FakeStreamingLlm(
        "DECISION: advance\n\n",
        "Let's switch to why you want this role.",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["ownership"],
                    "source": "resume",
                },
                {
                    "name": "skills",
                    "duration_minutes": 8,
                    "topics": ["Python"],
                    "source": "jd",
                },
            ]
        },
        llm,
        candidate_turns=["I already introduced myself."],
        max_probes_per_phase=8,
        target_duration_minutes=30,
    )
    async for _ in flow.generate_next_question_stream(
        "I owned checkout on the payments gateway."
    ):
        pass
    assert flow.phase_index == 0
    assert flow.probe_count == 1


def test_generic_outline_scales_to_thirty_minutes() -> None:
    scaled = scale_outline_to_duration(GENERIC_OUTLINE, 30)
    assert sum(phase["duration_minutes"] for phase in scaled["phases"]) == 30
    assert scaled["phases"][0]["name"] == "warm-up"
    assert scaled["phases"][0]["duration_minutes"] <= 3


def test_generic_outline_scales_to_selected_lengths() -> None:
    for minutes in (15, 30, 45):
        scaled = scale_outline_to_duration(GENERIC_OUTLINE, minutes)
        assert sum(phase["duration_minutes"] for phase in scaled["phases"]) == minutes


def test_warmup_does_not_leave_just_because_clock_moved() -> None:
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "warm-up",
                    "duration_minutes": 5,
                    "topics": ["background"],
                    "source": "generic",
                },
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["ownership"],
                    "source": "resume",
                },
            ]
        },
        FakeStreamingLlm(),
        max_probes_per_phase=8,
        target_duration_minutes=30,
    )
    flow.phase_started_at = time.monotonic() - 10 * 60
    assert flow._should_leave_phase() is False
    flow.probe_count = 1
    assert flow._should_leave_phase() is True


def test_extract_resume_projects_from_brief() -> None:
    projects = extract_resume_projects(
        "Jane Doe\nBackend Engineer\n\n"
        "Projects\n"
        "- Payments Gateway: checkout on AWS\n"
        "- Inventory Service: Redis and PostgreSQL\n"
        "- Mobile Analytics: event pipeline\n\n"
        "Skills\nPython, Kafka"
    )
    assert projects == [
        "Payments Gateway",
        "Inventory Service",
        "Mobile Analytics",
    ]


def test_enrich_outline_lists_every_resume_project() -> None:
    enriched = enrich_outline_with_resume(
        GENERIC_OUTLINE,
        "Projects\n- Payments Gateway: checkout\n- Inventory Service: stock sync",
    )
    topics = " ".join(enriched["phases"][1]["topics"])
    assert "Payments Gateway" in topics
    assert "Inventory Service" in topics


@pytest.mark.asyncio
async def test_does_not_jump_to_role_fit_while_projects_remain() -> None:
    llm = FakeStreamingLlm(
        "DECISION: advance\n\n",
        "Why do you want this role?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["Payments Gateway", "Inventory Service"],
                    "source": "resume",
                },
                {
                    "name": "role fit",
                    "duration_minutes": 5,
                    "topics": ["motivation"],
                    "source": "jd",
                },
            ]
        },
        llm,
        candidate_turns=["I already introduced myself."],
        interviewer_turns=["How did you shard Payments Gateway writes?"],
        resume_text=(
            "Projects\n- Payments Gateway: checkout\n- Inventory Service: stock sync"
        ),
        max_probes_per_phase=8,
        target_duration_minutes=15,
    )
    flow.probe_count = 2
    async for _ in flow.generate_next_question_stream(
        "I owned checkout on the payments gateway."
    ):
        pass
    assert flow.phase_index == 0
    prompt = llm.messages[0][0]["content"]
    assert "Inventory Service" in prompt
    assert "Projects still missing" in prompt


def test_extract_jd_requirements_includes_dsa() -> None:
    topics = extract_jd_requirements(
        "We need strong DSA, system design, and PostgreSQL.",
        ["Python"],
    )
    assert "Python" in topics
    assert "DSA" in topics
    assert "System design" in topics
    assert "SQL" in topics


def test_enrich_outline_adds_dsa_job_requirement() -> None:
    enriched = enrich_outline_with_jd(
        GENERIC_OUTLINE,
        "Looking for DSA and backend ownership.",
        ["System design"],
    )
    requirement_phase = next(
        phase for phase in enriched["phases"] if phase.get("intent") == "jd_requirement"
    )
    topics = " ".join(requirement_phase["topics"])
    assert "DSA" in topics
    assert "System design" in topics


@pytest.mark.asyncio
async def test_intro_followup_sets_project_focus() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "On Payments Gateway, which API did you own?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "warm-up",
                    "duration_minutes": 2,
                    "topics": ["background"],
                    "source": "generic",
                    "intent": "intro",
                }
            ]
        },
        llm,
        resume_text="Projects: Payments Gateway. Skills: Python.",
        job_description="Backend role with DSA.",
    )
    async for _ in flow.generate_next_question_stream(
        "I am a backend engineer and I built a payments gateway."
    ):
        pass
    prompt = llm.messages[0][0]["content"]
    assert "CURRENT SECTION: intro" in prompt
    assert "Payments Gateway" in prompt
    assert flow.focus_item == "Payments Gateway"


@pytest.mark.asyncio
async def test_advance_moves_to_next_resume_project_not_role_fit() -> None:
    llm = FakeStreamingLlm(
        "DECISION: advance\n\n",
        "Let's look at Inventory Service next. How did you keep stock consistent?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["Payments Gateway", "Inventory Service"],
                    "source": "resume",
                    "intent": "resume_project",
                },
                {
                    "name": "job requirements",
                    "duration_minutes": 8,
                    "topics": ["DSA"],
                    "source": "jd",
                    "intent": "jd_requirement",
                },
            ]
        },
        llm,
        candidate_turns=["I already introduced myself."],
        interviewer_turns=["How did you shard Payments Gateway writes?"],
        resume_text=(
            "Projects\n- Payments Gateway: checkout\n- Inventory Service: stock sync"
        ),
        job_description="Need DSA.",
        max_probes_per_phase=8,
        target_duration_minutes=30,
    )
    flow.focus_item = "Payments Gateway"
    flow.probe_count = 3
    async for _ in flow.generate_next_question_stream(
        "I owned checkout on the payments gateway."
    ):
        pass
    assert flow.phase_index == 0
    assert flow.focus_item == "Inventory Service"
    prompt = llm.messages[0][0]["content"]
    assert "CURRENT SECTION: resume_project" in prompt
    assert "DSA" in prompt
    assert "standalone" in prompt.lower()


@pytest.mark.asyncio
async def test_second_probe_moves_to_the_next_project() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "What tradeoff did you make on Payments Gateway?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "project deep-dive",
                    "duration_minutes": 10,
                    "topics": ["Payments Gateway", "Inventory Service"],
                    "source": "resume",
                    "intent": "resume_project",
                }
            ]
        },
        llm,
        candidate_turns=["I already introduced myself."],
        interviewer_turns=["How did you shard Payments Gateway writes?"],
        resume_text=(
            "Projects\n- Payments Gateway: checkout\n- Inventory Service: stock sync"
        ),
        target_duration_minutes=15,
    )
    flow.focus_item = "Payments Gateway"
    flow.probe_count = 1
    async for _ in flow.generate_next_question_stream(
        "I owned checkout on the payments gateway."
    ):
        pass
    assert flow.phase_index == 0
    assert flow.focus_item == "Inventory Service"
    assert "Payments Gateway" in flow._covered_projects()


@pytest.mark.asyncio
async def test_dsa_prompt_is_independent_of_projects() -> None:
    llm = FakeStreamingLlm(
        "DECISION: probe\n\n",
        "Given an unsorted array of integers, how would you find two numbers that add to a target in linear time?",
    )
    flow = InterviewFlow(
        {
            "phases": [
                {
                    "name": "job requirements",
                    "duration_minutes": 8,
                    "topics": ["Python", "DSA"],
                    "source": "jd",
                    "intent": "jd_requirement",
                }
            ]
        },
        llm,
        candidate_turns=["I already introduced myself.", "I owned checkout."],
        interviewer_turns=["How did you shard Payments Gateway writes?"],
        resume_text="Projects: Payments Gateway.",
        job_description="Need Python and DSA.",
        competencies=["Python"],
    )
    flow.focus_item = "DSA"
    async for _ in flow.generate_next_question_stream(
        "I used Redis for the checkout cache."
    ):
        pass
    prompt = llm.messages[0][0]["content"]
    assert "CURRENT SECTION: jd_requirement" in prompt
    assert "standalone" in prompt.lower()
    assert "Do not mention their projects" in prompt
    assert "Do not connect it to a project" in prompt
