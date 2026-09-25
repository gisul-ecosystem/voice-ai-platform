"""Sample-interview check: follow-ups name one real evidence gap."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "test_harness"))

from score_followup_targets import walk


def test_sample_interview_followups_name_one_evidence_bullet() -> None:
    rows = walk()
    probes = [
        row
        for row in rows
        if row["action"].startswith("PROBE_") or row["action"] == "ASK_BASELINE"
    ]
    assert probes, "expected competency follow-ups"
    for row in probes:
        topic = row["topic"]
        assert topic, row
        assert "," not in topic
        assert "when, where, or for whom" not in topic
        assert row["topic_line"].endswith(topic)
        assert topic in row["basis"]

    ownership = [row for row in probes if row["phase"] == "Service ownership"]
    assert ownership[0]["topic"] == "production ownership"
    assert ownership[0]["shape"] == "why"
    method = next(row for row in ownership if row["intent"] == "applied_understanding")
    assert method["topic"] == "technical approach"
    assert "establish_ownership" in method["covered"]

    reliability = [row for row in probes if row["phase"] == "Reliability"]
    assert reliability[0]["topic"] == "incident handling"
    thin = next(row for row in reliability if row["gap"] == "unclear")
    assert thin["shape"] == "why"
    assert "establish_context" in thin["missing"]
