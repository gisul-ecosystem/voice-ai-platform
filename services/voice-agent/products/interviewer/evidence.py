"""Evidence ledger: what has actually been proven, not how many questions were asked.

Coverage (coverage.py) tracks conversational intents. This tracks technical
substance: for each competency, which dimensions of evidence the candidate has
actually demonstrated. The policy engine probes the weakest dimension, so depth
is driven by what is still unproven rather than by a question counter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Slot states, weakest to strongest.
MISSING = "missing"
CLAIMED = "claimed"
DEMONSTRATED = "demonstrated"
CONFIRMED = "confirmed"

_ORDER = {MISSING: 0, CLAIMED: 1, DEMONSTRATED: 2, CONFIRMED: 3}


@dataclass(frozen=True)
class SlotSpec:
    key: str
    label: str
    # What the interviewer must hear before this slot counts as demonstrated.
    bar: str
    # Probe rung used when this slot is the weakest one.
    probe: str


# Role-agnostic technical evidence dimensions. These are evidence *requirements*,
# never question text -- the model writes the wording for whichever slot is weakest.
TECHNICAL_SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec(
        key="ownership",
        label="personal ownership",
        bar="what this candidate personally decided or built, not what the team did",
        probe="ownership",
    ),
    SlotSpec(
        key="approach",
        label="approach chosen",
        bar="the specific algorithm, data structure, pattern or design they used, by name",
        probe="specifying",
    ),
    SlotSpec(
        key="mechanism",
        label="how it works",
        bar="the internal mechanism, step by step, not just the name of the technique",
        probe="mechanism",
    ),
    SlotSpec(
        key="complexity_or_cost",
        label="complexity or cost",
        bar=(
            "the cost characteristics: time and space complexity, latency, "
            "throughput or resource cost, with the actual figure"
        ),
        probe="metric",
    ),
    SlotSpec(
        key="tradeoff",
        label="trade-off against alternatives",
        bar="why this option rather than a named alternative, and what it cost them",
        probe="tradeoff",
    ),
    SlotSpec(
        key="failure_mode",
        label="failure modes and edge cases",
        bar="where the approach breaks, which edge cases they handled, what happens at scale",
        probe="failure_mode",
    ),
    SlotSpec(
        key="optimization",
        label="optimisation path",
        bar="how they would make it faster or cheaper, and what that would cost elsewhere",
        probe="optimization",
    ),
    SlotSpec(
        key="measurement",
        label="measured outcome",
        bar="a number that moved, stated as from-value to to-value",
        probe="metric",
    ),
)

SLOTS_BY_KEY: dict[str, SlotSpec] = {spec.key: spec for spec in TECHNICAL_SLOTS}
SLOT_KEYS: tuple[str, ...] = tuple(spec.key for spec in TECHNICAL_SLOTS)

# Depth bars by seniority: how much of the ladder must be demonstrated.
_LEVEL_SLOTS: dict[str, tuple[str, ...]] = {
    "intern": ("ownership", "approach", "mechanism"),
    "junior": ("ownership", "approach", "mechanism", "complexity_or_cost"),
    "mid": (
        "ownership",
        "approach",
        "mechanism",
        "complexity_or_cost",
        "tradeoff",
        "measurement",
    ),
    "senior": SLOT_KEYS,
    "lead": SLOT_KEYS,
}


def slots_for_level(level: str | None) -> tuple[str, ...]:
    return _LEVEL_SLOTS.get((level or "mid").strip().lower(), _LEVEL_SLOTS["mid"])


@dataclass(frozen=True)
class DifficultyProfile:
    """What difficulty controls: how far up the evidence ladder the bar sits.

    It deliberately does NOT touch the probe cap -- that is the recruiter's
    "Maximum follow-ups" setting and must stay authoritative.
    """

    start_slot: int  # index into the required-slot ladder to open on
    max_slot: int | None  # highest slot index permitted, None for no ceiling


DIFFICULTY_PROFILES: dict[str, DifficultyProfile] = {
    # Stops at mechanism: never asks for cost or trade-offs.
    "foundational": DifficultyProfile(start_slot=0, max_slot=2),
    "applied": DifficultyProfile(start_slot=0, max_slot=4),
    # Opens past ownership and presses all the way to optimisation.
    "diagnostic": DifficultyProfile(start_slot=1, max_slot=None),
    "strategic": DifficultyProfile(start_slot=1, max_slot=None),
}


def difficulty_profile(difficulty: str | None) -> DifficultyProfile:
    return DIFFICULTY_PROFILES.get(
        (difficulty or "applied").strip().lower(), DIFFICULTY_PROFILES["applied"]
    )


@dataclass
class CompetencyLedger:
    competency_id: str
    required: list[str] = field(default_factory=list)
    states: dict[str, str] = field(default_factory=dict)
    probes_spent: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "competency_id": self.competency_id,
            "required": list(self.required),
            "states": dict(self.states),
            "probes_spent": self.probes_spent,
        }

    def status_of(self, key: str) -> str:
        return self.states.get(key, MISSING)

    def weakest_slot(self) -> str | None:
        """Next slot to probe.

        A slot the candidate has *claimed* but not demonstrated outranks one that
        is still untouched: an unsupported claim is the cheapest evidence to win
        and letting it stand is how buzzwords get scored as substance.
        """
        best: tuple[int, int] | None = None
        chosen: str | None = None
        for position, key in enumerate(self.required):
            rank = _ORDER.get(self.status_of(key), 0)
            if rank >= _ORDER[DEMONSTRATED]:
                continue
            score = (-rank, position)
            if best is None or score < best:
                best = score
                chosen = key
        return chosen

    def is_satisfied(self) -> bool:
        return all(
            _ORDER.get(self.status_of(key), 0) >= _ORDER[DEMONSTRATED]
            for key in self.required
        )

    def demonstrated_count(self) -> int:
        return sum(
            1
            for key in self.required
            if _ORDER.get(self.status_of(key), 0) >= _ORDER[DEMONSTRATED]
        )


def build_ledger(
    definition: dict[str, Any] | None,
    *,
    target_level: str | None = None,
    difficulty: str | None = None,
) -> dict[str, CompetencyLedger]:
    ledger: dict[str, CompetencyLedger] = {}
    if not isinstance(definition, dict):
        return ledger
    profile = difficulty_profile(difficulty)
    for item in definition.get("competencies") or []:
        if not isinstance(item, dict):
            continue
        competency_id = str(item.get("id") or "").strip()
        if not competency_id:
            continue
        required = list(_required_slots(item, target_level))
        if profile.max_slot is not None:
            required = required[: profile.max_slot + 1]
        # Always keep at least one slot, even for the narrowest difficulty.
        ledger[competency_id] = CompetencyLedger(
            competency_id=competency_id,
            required=required or list(_required_slots(item, target_level))[:1],
            states={},
        )
    return ledger


def _required_slots(competency: dict[str, Any], target_level: str | None) -> list[str]:
    configured = [
        str(value).strip().lower()
        for value in (competency.get("evidence_slots") or [])
        if str(value).strip().lower() in SLOTS_BY_KEY
    ]
    if configured:
        return configured
    level = str(competency.get("target_level") or target_level or "mid")
    slots = list(slots_for_level(level))
    # A preferred competency does not need the full depth ladder.
    if str(competency.get("importance") or "high").strip().lower() != "high":
        slots = slots[:3]
    return slots


def promote(
    ledger: dict[str, CompetencyLedger],
    *,
    competency_id: str | None,
    demonstrated: Iterable[str] = (),
    claimed: Iterable[str] = (),
) -> list[str]:
    """Advance slots and return the keys that actually moved."""
    entry = ledger.get(competency_id or "")
    if entry is None:
        return []
    moved: list[str] = []
    for key in claimed:
        moved.extend(_advance(entry, key, CLAIMED))
    for key in demonstrated:
        moved.extend(_advance(entry, key, DEMONSTRATED))
    return moved


def _advance(entry: CompetencyLedger, key: str, target: str) -> list[str]:
    slot = str(key or "").strip().lower()
    if slot not in SLOTS_BY_KEY or slot not in entry.required:
        return []
    current = entry.status_of(slot)
    if _ORDER[target] <= _ORDER.get(current, 0):
        # Re-demonstrating an already-demonstrated slot corroborates it.
        if target == DEMONSTRATED and current == DEMONSTRATED:
            entry.states[slot] = CONFIRMED
            return [slot]
        return []
    entry.states[slot] = target
    return [slot]


def ledger_brief(entry: CompetencyLedger | None) -> str:
    """Human-readable ledger for the turn prompt."""
    if entry is None or not entry.required:
        return "(no evidence requirements configured)"
    lines = []
    for key in entry.required:
        spec = SLOTS_BY_KEY[key]
        lines.append(f"- {spec.label}: {entry.status_of(key).upper()} — needs {spec.bar}")
    return "\n".join(lines)


def target_slot_brief(entry: CompetencyLedger | None) -> tuple[str, str]:
    """Return (slot_key, instruction) for the weakest unproven slot."""
    if entry is None:
        return "", "Ask one job-related question."
    key = entry.weakest_slot()
    if not key:
        return "", "All required evidence is in. Move on."
    spec = SLOTS_BY_KEY[key]
    return key, (
        f"Target evidence: {spec.label}. The answer must contain {spec.bar}. "
        f"Ask the one question most likely to produce exactly that."
    )
