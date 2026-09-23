from __future__ import annotations

import pytest

from products.interviewer.evidence import build_ledger
from products.interviewer.policy import outline_from_definition


def _definition(weights: list[float | None]) -> dict:
    return {
        "definition_id": "idef_weight_01",
        "time_policy": {"duration_minutes": 45},
        "competencies": [
            {
                "id": f"c{index}",
                "name": f"Competency {index}",
                "max_depth": 4,
                "max_probes": 3,
                "weight": weight,
            }
            for index, weight in enumerate(weights)
        ],
    }


def _minutes(outline: dict) -> list[int]:
    return [
        int(phase["duration_minutes"])
        for phase in outline["phases"]
        if phase.get("competency_id")
    ]


def test_weight_drives_time_allocation() -> None:
    outline = outline_from_definition(_definition([60.0, 20.0, 20.0]))
    minutes = _minutes(outline)
    # The 60% competency must get clearly more time than the 20% ones.
    assert minutes[0] > minutes[1]
    assert minutes[1] == minutes[2]


def test_equal_weights_split_evenly() -> None:
    minutes = _minutes(outline_from_definition(_definition([50.0, 50.0])))
    assert minutes[0] == minutes[1]


def test_missing_weights_fall_back_to_an_even_split() -> None:
    minutes = _minutes(outline_from_definition(_definition([None, None, None])))
    assert len(set(minutes)) == 1


def test_every_competency_keeps_a_usable_minimum() -> None:
    # A tiny weight must not starve a competency out of the interview.
    minutes = _minutes(outline_from_definition(_definition([95.0, 2.5, 2.5])))
    assert all(value >= 3 for value in minutes), minutes


@pytest.mark.parametrize(
    ("difficulty", "expected_present", "expected_absent"),
    [
        ("foundational", "mechanism", "tradeoff"),
        ("strategic", "optimization", None),
    ],
)
def test_difficulty_profiles_reach_the_ledger(
    difficulty: str, expected_present: str, expected_absent: str | None
) -> None:
    definition = {
        "definition_id": "idef_diff",
        "competencies": [{"id": "c1", "name": "Algorithms", "importance": "high"}],
    }
    required = build_ledger(definition, target_level="senior", difficulty=difficulty)["c1"].required
    assert expected_present in required
    if expected_absent:
        assert expected_absent not in required
