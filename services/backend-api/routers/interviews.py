"""
Interview planning endpoint -- Stage 1 of the two-stage question
generation design (see docs/implementation_plan.md section 1).

Calls the LLM node (Laptop 1, Ollama) with a JSON-schema-constrained
request to produce a structured InterviewOutline from a JD + resume.
"""
import os
import json
import logging
import re
import time
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from models.schemas import InterviewPlanRequest, InterviewOutline
from security.auth import require_worker_service

logger = logging.getLogger("backend-api.interviews")

router = APIRouter(prefix="/interviews", tags=["interviews"])

OUTLINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "phases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string", "enum": ["resume", "jd", "generic"]},
                    "intent": {
                        "type": "string",
                        "enum": [
                            "intro",
                            "resume_project",
                            "jd_requirement",
                            "role_fit",
                        ],
                    },
                },
                "required": [
                    "name",
                    "duration_minutes",
                    "topics",
                    "source",
                    "intent",
                ],
            },
        }
    },
    "required": ["phases"],
}

SYSTEM_PROMPT = (
    "You are an interview planner. Given a job description and a candidate's "
    "resume, produce a structured interview outline the live interviewer must "
    "follow in order. Each phase has name, duration_minutes, topics, source, "
    "and intent. Intent tells the live interviewer what kind of question to ask. "
    "Required order, do not skip or mix: "
    "1) intent=intro — short self-introduction only. "
    "2) intent=resume_project — every named resume project, product, or "
    "substantial piece of work, in resume order. Deep-dive projects here only. "
    "3) intent=jd_requirement — required job skills first (languages, APIs, "
    "SQL, system design, listed competencies). These are independent of resume "
    "projects. Do not write skill topics as 'DSA in Project X'. "
    "4) If the JD mentions DSA, data structures, algorithms, or a coding round, "
    "add a separate DSA topic (or a later jd_requirement phase named DSA). "
    "DSA questions are standalone algorithm/coding questions, not project follow-ups. "
    "5) intent=role_fit — only if minutes remain after projects, skills, and DSA. "
    "The live interviewer invents questions from resume, JD, and the last "
    "answer; you only plan coverage and intent. "
    "Recruiter length is 15, 30, or 45 minutes. duration_minutes must sum to it. "
    "15 minutes: 1 minute intro, then resume projects (every project, shallower "
    "questions), then remaining minutes on JD requirements such as DSA. "
    "30/45 minutes: same order with more depth. "
    "Prefer technical topics. Do not invent employers or projects. "
    "Output only the structure — no spoken questions."
)

_INTENT_VALUES = {"intro", "resume_project", "jd_requirement", "role_fit"}
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
    if listed in _INTENT_VALUES:
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


def extract_jd_requirement_topics(
    job_description: str, competencies: list[str] | None = None
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        key = label.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        found.append(label.strip())

    for item in competencies or []:
        add(str(item))
    text = job_description or ""
    for pattern, label in _JD_TOPIC_PATTERNS:
        if pattern.search(text):
            add(label)
    skills = [
        item
        for item in found
        if "dsa" not in item.lower() and "algorithm" not in item.lower()
    ]
    dsa = [item for item in found if item not in skills]
    return (skills + dsa)[:12]


def _merge_topics(existing: list, extra: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(existing or []) + extra:
        key = str(item).strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        merged.append(key)
        if len(merged) >= 20:
            break
    return merged or ["role skills"]


def finalize_interview_outline(
    parsed: dict,
    *,
    job_description: str,
    competencies: list[str] | None = None,
) -> dict:
    phases = [dict(phase) for phase in (parsed.get("phases") or [])]
    for phase in phases:
        src = str(phase.get("source") or "generic").strip().lower()
        if "resume" in src:
            phase["source"] = "resume"
        elif src in {"jd", "job"} or "job description" in src:
            phase["source"] = "jd"
        else:
            phase["source"] = "generic"
        phase["intent"] = infer_phase_intent(phase)
    required = extract_jd_requirement_topics(job_description, competencies)
    mentioned = " ".join(
        f"{phase.get('name') or ''} {' '.join(phase.get('topics') or [])}"
        for phase in phases
    ).lower()
    missing = [item for item in required if item.lower() not in mentioned]
    if missing:
        target = next(
            (phase for phase in phases if phase.get("intent") == "jd_requirement"),
            None,
        )
        if target is None:
            insert_at = len(phases)
            for index, phase in enumerate(phases):
                if phase.get("intent") == "role_fit":
                    insert_at = index
                    break
            phases.insert(
                insert_at,
                {
                    "name": "job requirements",
                    "duration_minutes": 6,
                    "topics": missing,
                    "source": "jd",
                    "intent": "jd_requirement",
                },
            )
        else:
            target["topics"] = _merge_topics(target.get("topics") or [], missing)
    return {"phases": phases}


@router.post(
    "/plan",
    response_model=InterviewOutline,
    dependencies=[Depends(require_worker_service)],
)
async def create_interview_plan(req: InterviewPlanRequest):
    llm_url = os.getenv("LLM_SERVICE_URL", "http://localhost:11434/v1").rstrip("/")
    timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    connect_s = float(os.getenv("HTTP_CONNECT_TIMEOUT_SECONDS", "5"))
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    provider = (os.getenv("LLM_PROVIDER") or "self_hosted").strip().lower()
    use_openai = provider in {"openai", "openai_api", "api"} or "api.openai.com" in llm_url
    model = os.getenv("LLM_MODEL_NAME", "qwen3:4b-instruct-2507-q8_0")
    if use_openai and (":" in model or model.lower().startswith("qwen")):
        model = "gpt-4o-mini"

    setup = req.interview_setup
    setup_context = ""
    if setup:
        setup_context = (
            f"\n\nINTERVIEW CONFIGURATION:\n"
            f"Title: {setup.title}\nRole: {setup.role}\n"
            f"Seniority: {setup.seniority}\nComplexity: {setup.difficulty}\n"
            f"Total duration: {setup.durationMinutes} minutes\n"
            f"Language: {setup.language}\n"
            f"Competencies: {', '.join(setup.competencies)}\n"
            "Set intent on every phase. Order: intro, resume projects, then "
            "independent job skills, then standalone DSA if the JD asks for it, "
            "then role_fit only if time remains. "
            f"Phase duration_minutes MUST sum to exactly {setup.durationMinutes} minutes. "
            "List every resume project. Compact 15-minute plans by asking fewer "
            "questions per project, not by dropping projects or JD requirements. "
            "Do not invent facts that are not in the JD or resume."
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"JD:\n{req.job_description}\n\nResume:\n{req.resume_text}"
                    f"{setup_context}"
                ),
            },
        ],
    }
    if use_openai:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "interview_outline",
                "strict": True,
                "schema": OUTLINE_SCHEMA,
            },
        }
        payload["messages"][0]["content"] += (
            " Reply with JSON only, matching keys phases[].name, "
            "duration_minutes, topics, source, intent."
        )
    else:
        payload["format"] = OUTLINE_SCHEMA

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=connect_s)) as client:
        try:
            resp = await client.post(
                f"{llm_url}/chat/completions",
                json=payload,
                headers=headers or None,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.error(
                "interview_plan_llm_failed",
                extra={
                    "event": "interview_plan_llm_failed",
                    "stage": "llm",
                    "latency_ms": latency_ms,
                    "error_type": type(e).__name__,
                },
            )
            raise HTTPException(status_code=502, detail=f"LLM service unreachable: {e}")

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.error(
            "interview_plan_invalid_provider_response",
            extra={"event": "interview_plan_invalid_provider_response"},
        )
        raise HTTPException(
            status_code=502,
            detail="LLM returned an invalid interview plan",
        ) from exc
    setup_skills = list(setup.competencies) if setup else []
    parsed = finalize_interview_outline(
        parsed,
        job_description=req.job_description,
        competencies=setup_skills,
    )
    try:
        outline = InterviewOutline(**parsed)
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail="LLM returned an invalid interview plan",
        ) from exc
    logger.info(
        "stage_latency",
        extra={
            "event": "stage_latency",
            "stage": "llm",
            "latency_ms": latency_ms,
            "endpoint": "/interviews/plan",
            "phase_count": len(outline.phases),
        },
    )
    return outline
