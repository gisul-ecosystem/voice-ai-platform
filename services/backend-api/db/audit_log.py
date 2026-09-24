"""Audit log persistence.

Guardrail: GUARDRAIL_AUDIT_LOG (default ON).
Records who changed config (weights, JD, competencies) and what automated
decisions the AI made (scoring outcomes, decisions), with timestamps.
Stored in MongoDB `audit_log` collection; never auto-deleted (retention
subject to legal hold requirements).

Config flag: GUARDRAIL_AUDIT_LOG (env, default ON).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from db.mongo import get_db

logger = logging.getLogger("backend-api.audit")


def _flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val not in {"0", "false", "off", "no"}


GUARDRAIL_AUDIT_LOG: bool = _flag("GUARDRAIL_AUDIT_LOG")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_audit_indexes() -> None:
    db = get_db()
    await db.audit_log.create_index([("event_type", 1), ("created_at", -1)])
    await db.audit_log.create_index([("actor_id", 1), ("created_at", -1)])
    await db.audit_log.create_index([("resource_id", 1), ("created_at", -1)])
    await db.audit_log.create_index([("created_at", -1)])


async def write_audit_event(
    *,
    event_type: str,
    actor_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Write a single audit log entry.

    Returns the audit_id on success, or "disabled"/"error" on failure.
    Never raises — audit failures must not block the main operation.

    Args:
        event_type: Category, e.g. "config_change", "ai_decision", "consent_recorded"
        actor_id: Who performed the action (admin user ID, "system", "ai_agent")
        resource_type: What was changed, e.g. "interview_definition", "session", "candidate"
        resource_id: The ID of the changed resource
        action: Human-readable description, e.g. "weight_updated", "jd_uploaded"
        before: Sanitised before-state (no PII text, only keys/IDs/scores)
        after: Sanitised after-state
        metadata: Any additional context (no PII)
    """
    if not GUARDRAIL_AUDIT_LOG:
        return "disabled"

    audit_id = f"aud_{uuid.uuid4().hex}"
    document = {
        "_id": audit_id,
        "audit_id": audit_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "before": before or {},
        "after": after or {},
        "metadata": metadata or {},
        "created_at": utc_now(),
    }
    try:
        await get_db().audit_log.insert_one(document)
        logger.info(
            "audit_event_written",
            extra={
                "event": "audit_event_written",
                "guardrail": "GUARDRAIL_AUDIT_LOG",
                "audit_id": audit_id,
                "event_type": event_type,
                "actor_id": actor_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
            },
        )
        return audit_id
    except Exception as exc:
        logger.error(
            "audit_event_write_failed",
            extra={
                "event": "audit_event_write_failed",
                "guardrail": "GUARDRAIL_AUDIT_LOG",
                "event_type": event_type,
                "error": str(exc),
            },
        )
        return "error"


async def log_config_change(
    *,
    actor_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Convenience wrapper for admin configuration changes."""
    return await write_audit_event(
        event_type="config_change",
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before=before,
        after=after,
        metadata=metadata,
    )


async def log_ai_decision(
    *,
    session_id: str,
    decision_type: str,
    competency_id: str | None = None,
    outcome: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Log an automated AI decision (scoring outcome, recommendation)."""
    return await write_audit_event(
        event_type="ai_decision",
        actor_id="ai_agent",
        resource_type="session",
        resource_id=session_id,
        action=decision_type,
        after={
            "competency_id": competency_id,
            "outcome": outcome,
            "confidence": confidence,
        },
        metadata=metadata,
    )


async def log_consent(
    *,
    candidate_id: str,
    session_id: str | None,
    consent_fields: list[str],
    policy_version: str,
) -> str:
    """Log that consent was recorded with which fields."""
    return await write_audit_event(
        event_type="consent_recorded",
        actor_id=candidate_id,
        resource_type="candidate",
        resource_id=candidate_id,
        action="consent_given",
        after={
            "consent_fields": consent_fields,
            "policy_version": policy_version,
            "session_id": session_id,
        },
    )
