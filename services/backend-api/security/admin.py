"""Tenant-scoped human administrator authentication."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status_code=403, detail="Insufficient scope")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def require_admin(
    authorization: str | None = Header(default=None),
) -> AdminPrincipal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Administrator token required")
    secret = (os.getenv("ADMIN_JWT_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Administrator auth is not configured")
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(
            secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise ValueError("signature")
        claims = json.loads(_decode(payload))
        if claims.get("exp", 0) <= time.time() or claims.get("aud") != "voice-platform":
            raise ValueError("claims")
        subject = str(claims["sub"])
        tenant_id = str(claims["tenant_id"])
        scopes = frozenset(str(claims.get("scope", "")).split())
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid administrator token") from exc
    return AdminPrincipal(subject, tenant_id, scopes)
