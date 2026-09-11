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
from fastapi import APIRouter, HTTPException
from models.schemas import InterviewPlanRequest, InterviewOutline

logger = logging.getLogger("backend-api.interviews")

router = APIRouter(prefix="/interviews", tags=["interviews"])

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "phases": {
            "type": "array",
            "items": {
                "type": "object",
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


@router.post("/plan", response_model=InterviewOutline)
async def create_interview_plan(req: InterviewPlanRequest):
    llm_url = os.getenv("LLM_SERVICE_URL", "http://localhost:11434/v1").rstrip("/")
    timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    connect_s = float(os.getenv("HTTP_CONNECT_TIMEOUT_SECONDS", "5"))

    payload = {
        # Ollama's OpenAI-compatible endpoint -- swap this model name for
        # the vLLM equivalent when moving to a real GPU server; the
        # request/response shape doesn't change.
        "model": os.getenv("LLM_MODEL_NAME", "qwen3:4b-instruct-2507-q8_0"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"JD:\n{req.job_description}\n\nResume:\n{req.resume_text}",
            },
        ],
        "format": OUTLINE_SCHEMA,  # Ollama's structured-output param name
    }

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=connect_s)) as client:
        try:
            resp = await client.post(f"{llm_url}/chat/completions", json=payload)
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
    content = resp.json()["choices"][0]["message"]["content"]
    outline = InterviewOutline(**json.loads(content))
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
