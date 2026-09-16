"""Compatibility entrypoint for the modular Racko customer-support product."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

from logging_config import configure_logging

load_dotenv()
configure_logging()

from clients.backend_client import (  # noqa: E402
    fetch_account_status,
    fetch_invoice_status,
    fetch_order_status,
)
from clients.context_client import retrieve_context  # noqa: E402
from products.customer_support.agent import RackoAgent as _ProductRackoAgent  # noqa: E402
from products.customer_support.flow import (  # noqa: E402
    ASK_ACCOUNT_ID,
    ASK_ORDER_ID,
    CLASSIFY_SYSTEM,
    ESCALATION_SPOKEN,
    GREETING,
    MAX_UNRESOLVED_ATTEMPTS,
    REPLY_SYSTEM,
    SupportFlow,
    extract_id,
    looks_like_id,
    parse_intent,
    parse_resolved,
    wants_human,
)
from products.customer_support.worker import (  # noqa: E402
    VoicePipelineAgent,
    entrypoint,
    run,
)
from voice_platform.chat import last_text  # noqa: E402


class RackoAgent(_ProductRackoAgent):
    """Backward-compatible constructor with patchable integration defaults."""

    def __init__(
        self,
        llm_client,
        *,
        session_id: str = "",
        fetch_account=None,
        fetch_invoice=None,
        fetch_order=None,
        retrieve=None,
    ) -> None:
        super().__init__(
            llm_client,
            session_id=session_id,
            fetch_account=fetch_account or fetch_account_status,
            fetch_invoice=fetch_invoice or fetch_invoice_status,
            fetch_order=fetch_order or fetch_order_status,
            retrieve=retrieve or retrieve_context,
        )


# Preserve the helper import surface used by existing scripts and tests.
_last_user_text = last_text
_parse_intent = parse_intent
_parse_resolved = parse_resolved
_looks_like_id = looks_like_id
_extract_id = extract_id
_wants_human = wants_human

__all__ = [
    "ASK_ACCOUNT_ID",
    "ASK_ORDER_ID",
    "CLASSIFY_SYSTEM",
    "ESCALATION_SPOKEN",
    "GREETING",
    "MAX_UNRESOLVED_ATTEMPTS",
    "REPLY_SYSTEM",
    "RackoAgent",
    "SupportFlow",
    "VoicePipelineAgent",
    "entrypoint",
    "run",
]


if __name__ == "__main__":
    run()
