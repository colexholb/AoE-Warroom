"""What to build against each unit. Hand-curated from common AoE2 counter knowledge.

The curated table now lives in ``data/counters.json``; this module loads it at import so
existing callers keep working unchanged.

Keys are the base unit names that appear in replays (a queue action for a Paladin is recorded
as "Knight"), so each entry covers the whole unit line. Counters name one unit per line too:
"Spearmen" means the spear line, "Militia line" the swordsmen, "Knights" the knight line.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).with_name("data") / "counters.json"
_counters_raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))

# unit -> counters, best first
UNIT_COUNTERS: dict[str, list[str]] = {
    name: entry["generic"] for name, entry in _counters_raw["counters"].items()
}

# Fallback when a unit isn't in the table (new DLC units etc.).
GROUP_COUNTERS: dict[str, list[str]] = _counters_raw["fallback"]


def counters_for(unit_name: str, group: str) -> list[str]:
    return UNIT_COUNTERS.get(unit_name) or GROUP_COUNTERS.get(group, [])


def combined_counters(units: list[tuple[str, str, float]], limit: int = 2) -> list[str]:
    """Best answers to a mix of (unit name, group, share): counters that hit more of the mix win."""
    score: dict[str, float] = {}
    for name, group, share in units:
        for rank, counter in enumerate(counters_for(name, group)):
            score[counter] = score.get(counter, 0) + share * (1.0 - 0.3 * rank)
    return [c for c, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]
