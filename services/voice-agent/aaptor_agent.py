"""Compatibility entrypoint for the modular Aaptor interviewer product."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

from logging_config import configure_logging  # noqa: E402

load_dotenv()
configure_logging()

from products.interviewer.agent import AaptorAgent  # noqa: E402
from products.interviewer.flow import (  # noqa: E402
    CLOSING_MESSAGE,
    FALLBACK_OPENING,
    MAX_PROBES_PER_PHASE,
    OPENING_SYSTEM,
    STAGE2_SYSTEM,
    InterviewFlow,
    parse_stage2,
    phase_topics,
)
from products.interviewer.worker import (  # noqa: E402
    GENERIC_OUTLINE,
    VoicePipelineAgent,
    build_outline,
    entrypoint,
    plan_inputs_from_job,
    run,
)
from voice_platform.chat import last_text  # noqa: E402

# Preserve the helper import surface used by existing scripts and tests.
_phase_topics = phase_topics
_parse_stage2 = parse_stage2
_last_user_text = last_text
_plan_inputs_from_job = plan_inputs_from_job
_build_outline = build_outline

__all__ = [
    "AaptorAgent",
    "CLOSING_MESSAGE",
    "FALLBACK_OPENING",
    "GENERIC_OUTLINE",
    "InterviewFlow",
    "MAX_PROBES_PER_PHASE",
    "OPENING_SYSTEM",
    "STAGE2_SYSTEM",
    "VoicePipelineAgent",
    "entrypoint",
    "run",
]


if __name__ == "__main__":
    run()
