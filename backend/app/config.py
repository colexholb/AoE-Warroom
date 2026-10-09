"""Settings, overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

GAME_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Games\Age of Empires 2 DE"))

# How many recent matches to pull per player (aoe2companion caps a page at 300).
HISTORY_SIZE = int(os.environ.get("AOE_HISTORY_SIZE", "300"))
# A recording that hasn't been written to for this long means the game is over.
LIVE_TIMEOUT_SECONDS = int(os.environ.get("AOE_LIVE_TIMEOUT", "90"))
# Your profile id. Auto-detected from your recordings when unset.
MY_PROFILE_ID = int(os.environ["AOE_PROFILE_ID"]) if os.environ.get("AOE_PROFILE_ID") else None
API_BASE = "https://data.aoe2companion.com/api"
USER_AGENT = "AoeWarroom-local/0.1 (personal match scouting tool)"


def savegame_dirs() -> list[Path]:
    """Every savegame folder (one per Steam / Xbox account that has played on this PC)."""
    if os.environ.get("AOE_SAVEGAME_DIR"):
        return [Path(os.environ["AOE_SAVEGAME_DIR"])]
    if not GAME_DIR.is_dir():
        return []
    return sorted(p / "savegame" for p in GAME_DIR.iterdir() if (p / "savegame").is_dir())
