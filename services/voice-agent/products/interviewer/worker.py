"""LiveKit worker lifecycle for the Aaptor interviewer product."""
from __future__ import annotations

import logging
import os
from typing import Any

from livekit.agents import AgentSession, JobContext, JobProcess, WorkerOptions, cli

from clients.backend_client import (
    fetch_interview_context,
    fetch_interview_definition,
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
from clients.tts.voice_policy import (
    log_tts_recovery,
    resolve_voice_policy,
    run_tts_preflight,
)
from products.interviewer.agent import AaptorAgent
from products.interviewer.brain_runtime import (
    BrainSessionBridge,
    definition_id_for_session,
    load_brain_initial_state,
)
from products.interviewer.policy import outline_from_definition
from products.interviewer.flow import (
    build_candidate_profile,
    extract_jd_requirements,
    extract_resume_projects,
    infer_phase_intent,
    order_job_topics,
)
from voice_platform.runtime import (
    attach_session_metrics,
    build_agent_session,
    load_inference_clients,
    prewarm_runtime,
)

logger = logging.getLogger("voice-agent.aaptor")


async def flush_pending_session_turns(
    session_id: str,
    pending: list[dict[str, Any]],
    *,
    reason: str,
) -> bool:
    """Persist queued turns in order. Stop on first failure so sequence stays intact."""
    if not session_id or not pending:
        return True
    while pending:
        item = pending[0]
        try:
            await record_session_turn(session_id, **item)
            pending.pop(0)
        except ServiceUnavailableError:
            logger.error(
                "turn_record_unavailable",
                extra={
                    "event": "turn_record_unavailable",
                    "reason": reason,
                    "session_id": session_id,
                    "turn_id": item.get("turn_id"),
                    "speaker": item.get("speaker"),
                    "sequence_number": item.get("sequence_number"),
                    "pending_count": len(pending),
                },
            )
            return False
    return True


GENERIC_OUTLINE = {
    "phases": [
        {
            "name": "warm-up",
            "duration_minutes": 2,
            "topics": ["background", "introduction"],
            "source": "generic",
            "intent": "intro",
        },
        {
            "name": "project deep-dive",
            "duration_minutes": 10,
            "topics": ["resume projects", "architecture", "implementation"],
            "source": "resume",
            "intent": "resume_project",
        },
        {
            "name": "job requirements",
            "duration_minutes": 8,
            "topics": ["role skills", "problem solving"],
            "source": "jd",
            "intent": "jd_requirement",
        },
        {
            "name": "role fit",
            "duration_minutes": 7,
            "topics": ["why this role", "motivation"],
            "source": "jd",
            "intent": "role_fit",
        },
    ]
}


ALLOWED_DURATIONS = (15, 30, 45)


class InterviewPlanUnavailableError(RuntimeError):
    """Raised when a published plan is required but cannot be used."""


def published_plan_required(
    *,
    definition_id: str | None,
    app_env: str | None = None,
    context_bound: bool = False,
) -> bool:
    if (definition_id or "").strip():
        return True
    # A job that carried a context_id was scheduled against a real interview.
    # Falling back to the generic outline here silently downgrades the whole
    # interviewer (no competencies, no evidence ledger) with no visible error.
    if context_bound:
        return True
    env = (app_env if app_env is not None else os.getenv("APP_ENV") or "development")
    return env.strip().lower() in {"production", "staging"}


def resolve_live_outline(
    *,
    interview_definition: dict | None,
    definition_id: str | None,
    app_env: str | None = None,
    context_bound: bool = False,
) -> tuple[dict | None, str]:
    """Return (outline, source). Outline is None when a local generated plan is allowed.

    Never falls back to GENERIC_OUTLINE when a published definition is bound, a
    context was bound, or the environment is production/staging.
    """
    require = published_plan_required(
        definition_id=definition_id,
        app_env=app_env,
        context_bound=context_bound,
    )
    if isinstance(interview_definition, dict) and interview_definition.get("competencies"):
        outline = outline_from_definition(interview_definition)
        if outline:
            return outline, "published_definition"
        raise InterviewPlanUnavailableError("definition_has_no_usable_plan")
    if require:
        raise InterviewPlanUnavailableError(
            "interview_context_unreachable"
            if context_bound and not definition_id
            else "published_definition_required"
        )
    return None, "generated_plan"


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


def enrich_outline_with_jd(
    outline: dict,
    job_description: str,
    competencies: list[str] | None = None,
) -> dict:
    """Inject JD/competency topics into the outline when phases do not already cover them.

    Competencies are assessment targets — they expand the required topic set via
    extract_jd_requirements; they must not be treated as already-covered exclusions.
    """
    required = extract_jd_requirements(job_description, competencies)
    if not required:
        return outline
    phases = [dict(phase) for phase in (outline or {}).get("phases") or []]
    mentioned = " ".join(
        f"{phase.get('name') or ''} {' '.join(phase.get('topics') or [])}"
        for phase in phases
    ).lower()
    missing = [name for name in required if name.lower() not in mentioned]
    if not missing:
        return {**outline, "phases": phases} if phases else outline
    target = None
    for phase in phases:
        if infer_phase_intent(phase) == "jd_requirement":
            target = phase
            break
    if target is None:
        insert_at = len(phases)
        for index, phase in enumerate(phases):
            if infer_phase_intent(phase) == "role_fit":
                insert_at = index
                break
        phases.insert(
            insert_at,
            {
                "name": "job requirements",
                "duration_minutes": 8,
                "topics": order_job_topics(missing),
                "source": "jd",
                "intent": "jd_requirement",
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
    target["topics"] = order_job_topics(merged)
    target["intent"] = "jd_requirement"
    return {**outline, "phases": phases}


def stamp_phase_intents(outline: dict) -> dict:
    phases = [dict(phase) for phase in (outline or {}).get("phases") or []]
    for phase in phases:
        phase["intent"] = infer_phase_intent(phase)
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


_WEAK_LIVEKIT_KEYS = frozenset({"devkey", "dev", "test", "changeme"})


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
    livekit_key = (os.getenv("LIVEKIT_API_KEY") or "").strip().lower()
    allow_weak = (os.getenv("LIVEKIT_ALLOW_WEAK_API_KEY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if livekit_key in _WEAK_LIVEKIT_KEYS and not allow_weak:
        raise RuntimeError(
            "LIVEKIT_API_KEY must not be a shared/dev placeholder "
            f"({livekit_key!r}) in production/staging; set a real LiveKit API "
            "key or set LIVEKIT_ALLOW_WEAK_API_KEY=true to keep current credentials"
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
    if published_plan_required(definition_id=None):
        raise InterviewPlanUnavailableError("generated_plan_not_allowed")
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
    pending_turns: list[dict[str, Any]] = []

    async def shutdown_session() -> None:
        try:
            if session_id:
                await flush_pending_session_turns(
                    session_id, pending_turns, reason="worker_shutdown"
                )
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

    # TTS clients + AgentSession are built after definition load so voice_policy pins apply.
    initial_state: dict = {}
    brain_bridge: BrainSessionBridge | None = None
    context_id = context_id_from_job(ctx)
    context: dict = {}
    context_fetch_failed = False
    if context_id:
        try:
            context = await fetch_interview_context(context_id)
        except ServiceUnavailableError:
            context_fetch_failed = True
            logger.warning(
                "interview_context_unavailable",
                extra={
                    "event": "interview_context_unavailable",
                    "context_id": context_id,
                },
            )
            context = {}
    explicit_definition_id = None
    if isinstance(context, dict):
        raw_definition = context.get("definition_id")
        if isinstance(raw_definition, str) and raw_definition.strip():
            explicit_definition_id = raw_definition.strip()
    if session_id:
        brain_state = await load_brain_initial_state(session_id)
        brain_has_turns = bool(
            brain_state.get("candidate_turns") or brain_state.get("interviewer_turns")
        )
        if brain_has_turns:
            initial_state = brain_state
            logger.info(
                "brain_state_restored",
                extra={
                    "event": "brain_state_restored",
                    "session_id": session_id,
                    "state_version": brain_state.get("brain_state_version"),
                },
            )
        else:
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
            # Keep brain version/ids even when turns came from transcript.
            if brain_state:
                initial_state = {
                    **initial_state,
                    "brain_state_version": brain_state.get("brain_state_version", 0),
                    "brain_active_question_id": brain_state.get(
                        "brain_active_question_id"
                    ),
                    "brain_asked_question_ids": list(
                        brain_state.get("brain_asked_question_ids") or []
                    ),
                }
        resolved_definition_id = definition_id_for_session(
            session_id,
            context_id,
            explicit_definition_id=explicit_definition_id,
        )
        brain_bridge = BrainSessionBridge(
            session_id=session_id,
            definition_id=resolved_definition_id,
            state_version=int(initial_state.get("brain_state_version") or 0),
            active_question_id=initial_state.get("brain_active_question_id"),
            asked_question_ids=list(
                initial_state.get("brain_asked_question_ids") or []
            ),
        )
        if explicit_definition_id:
            logger.info(
                "interview_definition_bound",
                extra={
                    "event": "interview_definition_bound",
                    "session_id": session_id,
                    "definition_id": explicit_definition_id,
                },
            )

    async def turn_sink(**turn) -> None:
        if not session_id:
            return
        pending_turns.append(dict(turn))
        await flush_pending_session_turns(
            session_id, pending_turns, reason="turn_sink"
        )

    async def status_sink(status: str, *, reason: str | None = None) -> None:
        if session_id:
            await flush_pending_session_turns(
                session_id, pending_turns, reason=f"status:{status}"
            )
            try:
                await report_session_status(session_id, status, reason=reason)
            except ServiceUnavailableError:
                logger.warning("status_report_unavailable", extra={"event": "status_report_unavailable"})

    target_duration_minutes = 30
    max_probes_per_phase = 2
    difficulty = "applied"
    language = "English"
    job_description = ""
    resume_text = ""
    competencies: list[str] = []
    if context_id and context:
        try:
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
                difficulty = str(setup.get("difficulty") or "applied").strip().lower()
                language = str(setup.get("language") or "English").strip() or "English"
                raw_skills = setup.get("competencies") or []
                if isinstance(raw_skills, list):
                    competencies = [
                        str(item).strip()
                        for item in raw_skills
                        if str(item).strip()
                    ]
        except (TypeError, ValueError):
            logger.warning(
                "interview_setup_unavailable",
                extra={"event": "interview_setup_unavailable"},
            )
    elif not context_id:
        try:
            job_description, resume_text = await plan_inputs_from_job(ctx)
        except ServiceUnavailableError:
            logger.warning(
                "interview_setup_unavailable",
                extra={"event": "interview_setup_unavailable"},
            )

    interview_definition: dict | None = None
    if explicit_definition_id:
        try:
            loaded = await fetch_interview_definition(explicit_definition_id)
            if isinstance(loaded, dict) and loaded.get("competencies"):
                interview_definition = loaded
                logger.info(
                    "interview_definition_loaded",
                    extra={
                        "event": "interview_definition_loaded",
                        "definition_id": explicit_definition_id,
                        "competency_count": len(loaded.get("competencies") or []),
                    },
                )
        except ServiceUnavailableError:
            logger.error(
                "interview_definition_unavailable",
                extra={
                    "event": "interview_definition_unavailable",
                    "definition_id": explicit_definition_id,
                    "session_id": session_id,
                },
            )
    voice_raw = (
        interview_definition.get("voice_policy")
        if isinstance(interview_definition, dict)
        else None
    )
    voice_policy = resolve_voice_policy(
        voice_raw if isinstance(voice_raw, dict) else None
    )
    clients = load_inference_clients(ctx, logger, voice_policy=voice_policy)
    try:
        await run_tts_preflight(
            clients.tts,
            voice_policy,
            session_id=session_id or None,
        )
    except ServiceUnavailableError as exc:
        action = log_tts_recovery(
            voice_policy,
            session_id=session_id or None,
            error=exc,
        )
        logger.error(
            "tts_preflight_failed",
            extra={
                "event": "tts_preflight_failed",
                "session_id": session_id,
                "action": action,
                "voice_id": voice_policy.voice_id,
                "provider": voice_policy.provider,
            },
        )
        if session_id:
            try:
                await report_session_status(
                    session_id,
                    "failed",
                    reason=f"tts_preflight_{action}"[:120],
                )
            except ServiceUnavailableError:
                logger.warning(
                    "status_report_unavailable",
                    extra={"event": "status_report_unavailable"},
                )
        raise
    vad = None
    proc = getattr(ctx, "proc", None)
    userdata = getattr(proc, "userdata", None) if proc is not None else None
    if isinstance(userdata, dict):
        vad = userdata.get("vad")
    session = build_agent_session(clients, vad=vad)
    attach_session_metrics(session, logger)
    try:
        outline, outline_source = resolve_live_outline(
            interview_definition=interview_definition,
            definition_id=explicit_definition_id,
            context_bound=bool(context_id) and context_fetch_failed,
        )
    except InterviewPlanUnavailableError as exc:
        logger.error(
            "interview_plan_unavailable",
            extra={
                "event": "interview_plan_unavailable",
                "reason": str(exc),
                "definition_id": explicit_definition_id,
                "session_id": session_id,
            },
        )
        if session_id:
            try:
                await report_session_status(
                    session_id,
                    "failed",
                    reason=str(exc)[:120],
                )
            except ServiceUnavailableError:
                logger.warning(
                    "status_report_unavailable",
                    extra={"event": "status_report_unavailable"},
                )
        raise
    if outline is None:
        outline = await build_outline(ctx)
        outline = enrich_outline_with_resume(outline, resume_text)
        outline = enrich_outline_with_jd(outline, job_description, competencies)
        outline = stamp_phase_intents(outline)
        outline = scale_outline_to_duration(outline, target_duration_minutes)
        outline_source = "generated_plan"
    logger.info(
        "stage1_outline",
        extra={
            "event": "stage1_outline",
            "phase_count": len(outline.get("phases") or []),
            "phases": [phase.get("name") for phase in (outline.get("phases") or [])],
            "source": outline_source,
        },
    )
    candidate_profile = build_candidate_profile(
        resume_text=resume_text,
        interview_setup=context.get("interview_setup") if isinstance(context, dict) else None,
        definition=interview_definition,
        existing=context.get("candidate_profile") if isinstance(context, dict) else None,
    )
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
            brain_bridge=brain_bridge,
            interview_definition=interview_definition,
            candidate_profile=candidate_profile,
            language=language,
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


def prewarm(proc: JobProcess) -> None:
    """Load Silero VAD once per job process before the first room join."""
    prewarm_runtime(proc)
    logger.info(
        "worker_prewarmed",
        extra={"event": "worker_prewarmed", "vad": True},
    )


def run() -> None:
    validate_startup_configuration()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "aaptor"),
            port=int(os.getenv("AAPTOR_WORKER_PORT", "8081")),
            # Default 0.7 is based on whole-machine CPU; on a dev box with
            # unrelated apps running, that falsely marks the worker "at
            # capacity" and it refuses to join new interview rooms.
            load_threshold=float(os.getenv("AAPTOR_LOAD_THRESHOLD", "0.95")),
        )
    )


if __name__ == "__main__":
    run()
