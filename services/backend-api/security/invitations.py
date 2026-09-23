"""Small signed invitation format with no external JWT dependency."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from fastapi import HTTPException


def _secret() -> bytes:
    value = (os.getenv("INTERVIEW_INVITATION_SECRET") or "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail="Interview invitation signing is not configured",
        )
    return value.encode()


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_invitation(
    *,
    interview_id: str,
    context_id: str,
    candidate_id: str,
    expires_at: int,
) -> str:
    payload = {
        "jti": f"inv_{uuid.uuid4().hex}",
        "interview_id": interview_id,
        "context_id": context_id,
        "candidate_id": candidate_id,
        "exp": expires_at,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _encode(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_invitation(token: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        expected = _encode(
            hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_decode(encoded))
        if not isinstance(payload, dict) or int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired")
        for field in ("jti", "interview_id", "context_id", "candidate_id"):
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise ValueError(field)
        return payload
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=401,
            detail="Interview invitation is invalid or expired",
        ) from exc
