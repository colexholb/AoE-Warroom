"""Settings, overridable through environment variables."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

GAME_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Games\Age of Empires 2 DE"))
# Replay database and civ icons. In AppData so a packaged exe never writes next to itself.
CACHE_DIR = Path(os.environ.get("AOE_CACHE_DIR")
                 or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AoE Warroom" / "cache")
# Where the cache lived before it moved to AppData.
LEGACY_CACHE_DIR = Path(__file__).parent.parent / "cache"

# How many recent matches to pull per player (aoe2companion caps a page at 300).
HISTORY_SIZE = int(os.environ.get("AOE_HISTORY_SIZE", "300"))
# A recording that hasn't been written to for this long means the game is over.
LIVE_TIMEOUT_SECONDS = int(os.environ.get("AOE_LIVE_TIMEOUT", "90"))
# Your profile id. When unset: the one picked in the UI, else auto-detected from recordings.
MY_PROFILE_ID = int(os.environ["AOE_PROFILE_ID"]) if os.environ.get("AOE_PROFILE_ID") else None
API_BASE = "https://data.aoe2companion.com/api"
USER_AGENT = "AoeWarroom-local/0.1 (personal match scouting tool)"


def cache_dir() -> Path:
    """The cache folder, created on first use. A cache from the old in-repo location is
    copied over once so analyzed replays aren't downloaded again (the old folder can be deleted)."""
    if not CACHE_DIR.exists() and LEGACY_CACHE_DIR.is_dir():
        try:
            shutil.copytree(LEGACY_CACHE_DIR, CACHE_DIR)
            log.info("copied cache from %s to %s", LEGACY_CACHE_DIR, CACHE_DIR)
        except OSError as e:
            log.warning("could not move old cache (%s); starting a fresh one", e)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def settings_path() -> Path:
    return CACHE_DIR.parent / "settings.json"


def load_settings() -> dict:
    """Choices made in the UI (e.g. which profile is you). Missing or broken file = defaults."""
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**changes) -> None:
    """Merge `changes` into the settings file; a None value removes that key."""
    settings = {k: v for k, v in {**load_settings(), **changes}.items() if v is not None}
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")


def savegame_dirs() -> list[Path]:
    """Every savegame folder (one per Steam / Xbox account that has played on this PC)."""
    if os.environ.get("AOE_SAVEGAME_DIR"):
        return [Path(os.environ["AOE_SAVEGAME_DIR"])]
    if not GAME_DIR.is_dir():
        return []
    return sorted(p / "savegame" for p in GAME_DIR.iterdir() if (p / "savegame").is_dir())
