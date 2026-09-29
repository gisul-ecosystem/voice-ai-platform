"""Weight -> behaviour formula (spec 4.1) — the single tunable source of truth.

Converts an admin's per-competency weight (0-100, mass-normalized to 100) into
deterministic interview behaviour: required questions, probe bounds, depth
target, and per-competency time budget. Constants live here only — never in
call sites. Admins only ever move a weight slider; they never see this
formula.
"""
from __future__ import annotations

# --- Tunable constants (spec 4.1 defaults) ---------------------------------
QUESTIONS_BASE = 1.0
QUESTIONS_SPAN = 3.0  # weight 100 -> 1 + 3 = 4 questions
PROBES_BASE = 1.0
PROBES_SPAN = 3.0  # weight 100 -> 1 + 3 = 4 probes
MIN_PROBES = 1
DEPTH_TARGET_BASE = 0.55
DEPTH_TARGET_SPAN = 0.35  # weight 100 -> 0.90

_WEIGHT_MIN = 0.0
_WEIGHT_MAX = 100.0


def _clamp_weight(weight: float) -> float:
    return max(_WEIGHT_MIN, min(_WEIGHT_MAX, float(weight)))


def _round_half_up(value: float) -> int:
    # Avoid banker's rounding surprises: spec's round() reads as half-up.
    return int(value + 0.5)


def required_questions(weight: float) -> int:
    """1 question at weight 0, 4 at weight 100 (spec 4.1)."""
    return max(1, _round_half_up(QUESTIONS_BASE + (_clamp_weight(weight) / 100.0) * QUESTIONS_SPAN))


def max_probes(weight: float) -> int:
    """1 probe at weight 0, 4 at weight 100 (spec 4.1)."""
    return max(1, _round_half_up(PROBES_BASE + (_clamp_weight(weight) / 100.0) * PROBES_SPAN))


def min_probes(weight: float) -> int:
    """min_probes is constant at 1 regardless of weight (spec 4.1)."""
    return MIN_PROBES


def depth_target(weight: float) -> float:
    """0.55 at weight 0, 0.90 at weight 100 (spec 4.1)."""
    return round(DEPTH_TARGET_BASE + (_clamp_weight(weight) / 100.0) * DEPTH_TARGET_SPAN, 2)


def time_budget_minutes(
    weight: float,
    total_weight: float,
    section_time_budget: float,
) -> float:
    """Share of the section time budget proportional to weight (spec 4.1)."""
    if total_weight <= 0 or section_time_budget <= 0:
        return 0.0
    return round((_clamp_weight(weight) / float(total_weight)) * float(section_time_budget), 2)


def allocate_section_time(
    weights: list[float],
    section_time_budget: float,
) -> list[float]:
    """Distribute a section's time budget across competencies by weight.

    Equal split when weights carry no mass. Drift is corrected on the last
    item so the full budget is allocated exactly once.
    """
    if not weights:
        return []
    if section_time_budget <= 0:
        return [0.0] * len(weights)
    total = sum(max(0.0, float(weight)) for weight in weights)
    if total <= 0:
        base = round(float(section_time_budget) / len(weights), 2)
        minutes = [base] * len(weights)
    else:
        minutes = [
            round((max(0.0, float(weight)) / total) * float(section_time_budget), 2)
            for weight in weights
        ]
    drift = round(float(section_time_budget) - sum(minutes), 2)
    minutes[-1] = round(minutes[-1] + drift, 2)
    return minutes


def normalize_weights(raw_weights: list[float]) -> list[float]:
    """Normalize raw slider values (each 0-100) to a mass of exactly 100.

    Equal split when the raw values carry no mass. Drift is corrected on the
    last item. Values are clamped to [0, 100] before normalizing.
    """
    if not raw_weights:
        return []
    clamped = [_clamp_weight(weight) for weight in raw_weights]
    total = sum(clamped)
    if total <= 0:
        base = round(100.0 / len(clamped), 2)
        weights = [base] * len(clamped)
    else:
        weights = [round((weight / total) * 100.0, 2) for weight in clamped]
    drift = round(100.0 - sum(weights), 2)
    weights[-1] = round(weights[-1] + drift, 2)
    return weights
