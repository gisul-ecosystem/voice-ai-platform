"""
Interview planning endpoint -- Stage 1 of the two-stage question
generation design (see docs/implementation_plan.md section 1).

Calls the LLM node (Laptop 1, Ollama) with a JSON-schema-constrained
request to produce a structured InterviewOutline from a JD + resume.
"""
import os
import json
import logging
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
                },
                "required": ["name", "duration_minutes", "topics", "source"],
            },
        }
    },
    "required": ["phases"],
}

SYSTEM_PROMPT = (
    "You are an interview planner. Given a job description and a candidate's "
    "resume, produce a structured interview outline: a sequence of phases "
    "(e.g. warm-up, resume deep-dive, core skill probe, scenario/problem-solving, "
    "behavioral, close), each with a duration, topics to cover, and whether "
    "that phase's content is derived from the resume, the JD, or generic "
    "methodology. Output only the structure -- do not write actual questions "
    "yet, that happens per-turn during the live interview."
)


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
            "Build phases around these job-related competencies and keep their "
            "combined duration within the configured total."
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
            "duration_minutes, topics, source."
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
    for phase in parsed.get("phases") or []:
        src = str(phase.get("source") or "generic").strip().lower()
        if "resume" in src:
            phase["source"] = "resume"
        elif src in {"jd", "job"} or "job description" in src:
            phase["source"] = "jd"
        else:
            phase["source"] = "generic"
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
