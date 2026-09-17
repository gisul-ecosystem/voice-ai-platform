"""LiveKit worker lifecycle for the Aaptor interviewer product."""
from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from clients.backend_client import (
    fetch_interview_context,
    fetch_interview_plan,
    fetch_session_state,
    record_session_turn,
    report_session_status,
)
from clients.errors import ServiceUnavailableError
from clients.inference import parse_room_metadata
from clients.llm import get_llm_client
from clients.stt import get_stt_client
from clients.tts import get_tts_client
from products.interviewer.agent import AaptorAgent
from products.interviewer.flow import extract_resume_projects
from voice_platform.runtime import (
    attach_session_metrics,
    build_agent_session,
    load_inference_clients,
)

logger = logging.getLogger("voice-agent.aaptor")

GENERIC_OUTLINE = {
    "phases": [
        {
            "name": "warm-up",
            "duration_minutes": 2,
            "topics": ["background", "introduction"],
            "source": "generic",
        },
        {
            "name": "project deep-dive",
            "duration_minutes": 10,
            "topics": ["resume projects", "architecture", "implementation"],
            "source": "resume",
        },
        {
            "name": "skills",
            "duration_minutes": 8,
            "topics": ["role skills", "problem solving"],
            "source": "jd",
        },
        {
            "name": "role fit",
            "duration_minutes": 7,
            "topics": ["why this role", "motivation"],
            "source": "jd",
        },
    ]
}


ALLOWED_DURATIONS = (15, 30, 45)


def normalize_duration_minutes(value: int | None) -> int:
    minutes = int(value or 30)
    if minutes in ALLOWED_DURATIONS:
        return minutes
    return min(ALLOWED_DURATIONS, key=lambda option: abs(option - minutes))


def normalize_probe_count(value: object, default: int = 2) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, min(int(value), 3))
    except (TypeError, ValueError):
        return default


def _is_warmup_name(name: str) -> bool:
    lowered = (name or "").lower()
    return any(token in lowered for token in ("warm", "intro", "opening"))


def enrich_outline_with_resume(outline: dict, resume_text: str) -> dict:
    projects = extract_resume_projects(resume_text)
    if not projects:
        return outline
    phases = [dict(phase) for phase in (outline or {}).get("phases") or []]
    if not phases:
        return {
            **outline,
            "phases": [
                {
                    "name": "resume projects",
                    "duration_minutes": 10,
                    "topics": projects,
                    "source": "resume",
                }
            ],
        }
    mentioned = " ".join(
        f"{phase.get('name') or ''} {' '.join(phase.get('topics') or [])}"
        for phase in phases
    ).lower()
    missing = [name for name in projects if name.lower() not in mentioned]
    if not missing:
        return {**outline, "phases": phases}
    target = None
    for phase in phases:
        name = str(phase.get("name") or "").lower()
        source = str(phase.get("source") or "").lower()
        if "project" in name or source == "resume":
            target = phase
            break
    if target is None:
        insert_at = 1 if _is_warmup_name(str(phases[0].get("name") or "")) else 0
        phases.insert(
            insert_at,
            {
                "name": "resume projects",
                "duration_minutes": 10,
                "topics": projects,
                "source": "resume",
            },
        )
        return {**outline, "phases": phases}
    topics = list(target.get("topics") or [])
    merged: list[str] = []
    seen: set[str] = set()
    for item in missing + topics:
        key = str(item).strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        merged.append(key)
    target["topics"] = merged
    return {**outline, "phases": phases}


def scale_outline_to_duration(outline: dict, total_minutes: int) -> dict:
    phases = list((outline or {}).get("phases") or [])
    if not phases:
        return outline
    target = normalize_duration_minutes(total_minutes)
    weights = [max(int(phase.get("duration_minutes") or 0), 1) for phase in phases]
    current = sum(weights)
    remaining = target
    scaled = []
    for index, phase in enumerate(phases):
        warmup = _is_warmup_name(str(phase.get("name") or ""))
        floor = 1 if warmup else 3
        if index == len(phases) - 1:
            minutes = max(floor, remaining)
        else:
            minutes = max(floor, round(weights[index] * target / current))
            remaining -= minutes
        scaled.append({**phase, "duration_minutes": minutes})
    return {**outline, "phases": scaled}


def validate_startup_configuration() -> None:
    if (os.getenv("APP_ENV") or "development").strip().lower() not in {
        "production",
        "staging",
    }:
        return
    required = (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "VOICE_AGENT_SERVICE_TOKEN",
    )
    missing = [name for name in required if not (os.getenv(name) or "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required voice-agent settings: " + ", ".join(sorted(missing))
        )
    # Provider factories perform service/provider validation and enforce API keys.
    get_llm_client()
    get_stt_client()
    get_tts_client()


VoicePipelineAgent = AgentSession


def context_id_from_job(ctx: JobContext) -> str | None:
    metadata = job_metadata(ctx)
    value = metadata.get("context_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def job_metadata(ctx: JobContext) -> dict:
    job = getattr(ctx, "job", None)
    raw = getattr(job, "metadata", None) or getattr(ctx.room, "metadata", None) or ""
    return parse_room_metadata(raw)


async def plan_inputs_from_job(ctx: JobContext) -> tuple[str, str]:
    context_id = context_id_from_job(ctx)
    if context_id:
        context = await fetch_interview_context(context_id)
        return (
            str(context.get("job_description") or "").strip(),
            str(context.get("resume_text") or "").strip(),
        )
    if (os.getenv("APP_ENV") or "development").lower() not in {
        "production",
        "staging",
    }:
        return (
            (os.getenv("JOB_DESCRIPTION") or "").strip(),
            (os.getenv("RESUME_TEXT") or "").strip(),
        )
    return "", ""


async def build_outline(ctx: JobContext) -> dict:
    try:
        context_id = context_id_from_job(ctx)
        context = await fetch_interview_context(context_id) if context_id else {}
        if context:
            job_description = str(context.get("job_description") or "").strip()
            resume = str(context.get("resume_text") or "").strip()
            interview_setup = context.get("interview_setup")
        else:
            job_description, resume = await plan_inputs_from_job(ctx)
            interview_setup = None
    except ServiceUnavailableError:
        logger.exception(
            "interview_context_fetch_failed",
            extra={"event": "interview_context_fetch_failed"},
        )
        return GENERIC_OUTLINE
    if not job_description or not resume:
        logger.warning(
            "plan_inputs_missing",
            extra={
                "event": "plan_inputs_missing",
                "has_jd": bool(job_description),
                "has_resume": bool(resume),
            },
        )
        return GENERIC_OUTLINE
    try:
        return await fetch_interview_plan(
            job_description,
            resume,
            interview_setup if isinstance(interview_setup, dict) else None,
        )
    except ServiceUnavailableError:
        logger.exception("stage1_plan_failed", extra={"event": "stage1_plan_failed"})
        return GENERIC_OUTLINE


async def entrypoint(ctx: JobContext) -> None:
    if hasattr(ctx, "log_context_fields"):
        ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("session_start", extra={"event": "session_start", "room": ctx.room.name})
    await ctx.connect()

    metadata = job_metadata(ctx)
    session_id = str(metadata.get("session_id") or "").strip()

    async def shutdown_session() -> None:
        try:
            if session_id:
                await report_session_status(
                    session_id,
                    "abandoned",
                    reason="worker_shutdown",
                )
        except ServiceUnavailableError:
            logger.warning(
                "session_shutdown_status_unavailable",
                extra={"event": "session_shutdown_status_unavailable"},
            )

    if hasattr(ctx, "add_shutdown_callback"):
        ctx.add_shutdown_callback(shutdown_session)

    clients = load_inference_clients(ctx, logger)
    outline = await build_outline(ctx)
    logger.info(
        "stage1_outline",
        extra={
            "event": "stage1_outline",
            "phase_count": len(outline.get("phases") or []),
            "phases": [phase.get("name") for phase in (outline.get("phases") or [])],
        },
    )

    session = build_agent_session(clients)
    attach_session_metrics(session, logger)
    initial_state: dict = {}
    if session_id:
        try:
            stored = await fetch_session_state(session_id)
            turns = stored.get("turns") if isinstance(stored, dict) else []
            if isinstance(turns, list) and turns:
                phase_index = max(
                    (
                        int(turn.get("phase_index", 0))
                        for turn in turns
                        if isinstance(turn, dict)
                    ),
                    default=0,
                )
                candidate_turns = [
                    str(turn.get("text") or "")
                    for turn in turns
                    if isinstance(turn, dict)
                    and turn.get("speaker") == "candidate"
                    and turn.get("text")
                ]
                interviewer_turns = [
                    str(turn.get("text") or "")
                    for turn in turns
                    if isinstance(turn, dict)
                    and turn.get("speaker") == "agent"
                    and turn.get("text")
                ]
                probe_count = sum(
                    1
                    for turn in turns
                    if isinstance(turn, dict)
                    and turn.get("speaker") == "candidate"
                    and int(turn.get("phase_index", 0)) == phase_index
                )
                initial_state = {
                    "initial_phase_index": phase_index,
                    "initial_probe_count": probe_count,
                    "candidate_turns": candidate_turns,
                    "interviewer_turns": interviewer_turns,
                    "initial_sequence_number": max(
                        (
                            int(turn.get("sequence_number", 0))
                            for turn in turns
                            if isinstance(turn, dict)
                        ),
                        default=0,
                    ),
                }
        except ServiceUnavailableError:
            logger.exception(
                "session_restore_failed",
                extra={"event": "session_restore_failed"},
            )

    async def turn_sink(**turn) -> None:
        if session_id:
            try:
                await record_session_turn(session_id, **turn)
            except ServiceUnavailableError:
                logger.warning("turn_record_unavailable", extra={"event": "turn_record_unavailable"})

    async def status_sink(status: str, *, reason: str | None = None) -> None:
        if session_id:
            try:
                await report_session_status(session_id, status, reason=reason)
            except ServiceUnavailableError:
                logger.warning("status_report_unavailable", extra={"event": "status_report_unavailable"})

    target_duration_minutes = 30
    max_probes_per_phase = 2
    job_description = ""
    resume_text = ""
    competencies: list[str] = []
    context_id = context_id_from_job(ctx)
    if context_id:
        try:
            context = await fetch_interview_context(context_id)
            job_description = str(context.get("job_description") or "").strip()
            resume_text = str(context.get("resume_text") or "").strip()
            setup = context.get("interview_setup")
            if isinstance(setup, dict):
                target_duration_minutes = normalize_duration_minutes(
                    setup.get("durationMinutes")
                )
                max_probes_per_phase = normalize_probe_count(
                    setup.get("maxProbesPerPhase")
                )
                raw_skills = setup.get("competencies") or []
                if isinstance(raw_skills, list):
                    competencies = [
                        str(item).strip()
                        for item in raw_skills
                        if str(item).strip()
                    ]
        except (ServiceUnavailableError, TypeError, ValueError):
            logger.warning(
                "interview_setup_unavailable",
                extra={"event": "interview_setup_unavailable"},
            )
    else:
        try:
            job_description, resume_text = await plan_inputs_from_job(ctx)
        except ServiceUnavailableError:
            logger.warning(
                "interview_setup_unavailable",
                extra={"event": "interview_setup_unavailable"},
            )

    outline = enrich_outline_with_resume(outline, resume_text)
    outline = scale_outline_to_duration(outline, target_duration_minutes)
    await session.start(
        agent=AaptorAgent(
            outline,
            clients.llm,
            max_probes_per_phase=max_probes_per_phase,
            job_description=job_description,
            resume_text=resume_text,
            competencies=competencies,
            target_duration_minutes=target_duration_minutes,
            initial_state=initial_state,
            turn_sink=turn_sink,
            status_sink=status_sink,
        ),
        room=ctx.room,
    )
    if session_id:
        try:
            await report_session_status(session_id, "live")
        except ServiceUnavailableError:
            logger.exception(
                "session_live_status_failed",
                extra={"event": "session_live_status_failed"},
            )


def run() -> None:
    validate_startup_configuration()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "aaptor"),
            port=int(os.getenv("AAPTOR_WORKER_PORT", "8081")),
        )
    )


if __name__ == "__main__":
    run()
