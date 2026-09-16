"""
Mock Tool & Integration layer for Racko CS.

Hardcoded/deterministic fake account and order payloads so the orchestrator
can call a tool and use the result. No CRM behind these endpoints.
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter

logger = logging.getLogger("backend-api.tools")

router = APIRouter(prefix="/tools", tags=["tools"])

_ACCOUNT_STATUSES = ("active", "suspended")
_PLANS = ("starter", "pro", "business")
_ORDER_STATUSES = ("placed", "shipped", "delivered")
_CARRIERS = ("Northline", "ParcelGo", "QuickPost")


def _stable_index(key: str, n: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % n


@router.get("/account/{account_id}")
def get_account(account_id: str) -> dict:
    status = _ACCOUNT_STATUSES[_stable_index(account_id, len(_ACCOUNT_STATUSES))]
    plan = _PLANS[_stable_index(f"{account_id}:plan", len(_PLANS))]
    payload = {
        "account_id": account_id,
        "status": status,
        "plan": plan,
        "balance_due_usd": round(_stable_index(f"{account_id}:bal", 12000) / 100.0, 2),
        "next_renewal": "2026-10-01",
    }
    logger.info(
        "tool_account",
        extra={"event": "tool_account", "account_id": account_id, "status": payload["status"]},
    )
    return payload


@router.get("/order/{order_id}")
def get_order(order_id: str) -> dict:
    status = _ORDER_STATUSES[_stable_index(order_id, len(_ORDER_STATUSES))]
    payload = {
        "order_id": order_id,
        "status": status,
        "carrier": _CARRIERS[_stable_index(f"{order_id}:carrier", len(_CARRIERS))],
        "eta": f"{1 + _stable_index(f'{order_id}:eta', 8)} business days",
        "item_count": 1 + _stable_index(f"{order_id}:items", 4),
    }
    logger.info(
        "tool_order",
        extra={"event": "tool_order", "order_id": order_id, "status": payload["status"]},
    )
    return payload


@router.get("/invoice/{invoice_id}")
def get_invoice(invoice_id: str) -> dict:
    idx = _stable_index(invoice_id, 3)
    payload = {
        "invoice_id": invoice_id,
        "status": ("paid", "open", "overdue")[idx],
        "amount_usd": round(29.0 + idx * 40.0, 2),
        "issued_on": "2026-09-01",
    }
    logger.info(
        "tool_invoice",
        extra={"event": "tool_invoice", "invoice_id": invoice_id, "status": payload["status"]},
    )
    return payload
