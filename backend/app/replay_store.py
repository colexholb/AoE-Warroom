"""Download, analyze and cache past games' replays (SQLite, one row per match)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sqlite3
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import config
from .replay import analyze_recording, strategy_dict

log = logging.getLogger(__name__)

REPLAY_URL = "https://aoe.ms/replay/"
# Retry replays that weren't available after this long (uploads can lag behind the match).
MISSING_RETRY_SECONDS = 6 * 3600
# Bump when replay.py's output changes so old cached rows get re-analyzed.
ANALYZER_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    key TEXT PRIMARY KEY,         -- "api:<match id>" or "local:<file name>"
    status TEXT NOT NULL,         -- ok | missing | skipped (not a Dark Age start)
    analyzer INTEGER NOT NULL,
    checked_at REAL NOT NULL,
    started TEXT,
    map_name TEXT,
    game_seconds INTEGER,
    players TEXT                  -- JSON list of per-player strategy dicts
);
CREATE TABLE IF NOT EXISTS player_games (
    profile_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    started TEXT,
    PRIMARY KEY (profile_id, key)
);
CREATE INDEX IF NOT EXISTS player_games_started ON player_games (profile_id, started);
"""


class ReplayStore:
    def __init__(self) -> None:
        self._db = sqlite3.connect(config.cache_dir() / "warroom.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def get(self, key: str) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute("SELECT * FROM games WHERE key = ?", (key,)).fetchone()

    def put_ok(self, key: str, started: datetime | None, map_name: str | None,
               game_seconds: int, players: list[dict]) -> None:
        started_s = started.isoformat() if started else None
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO games VALUES (?, 'ok', ?, ?, ?, ?, ?, ?)",
                (key, ANALYZER_VERSION, time.time(), started_s, map_name, game_seconds, json.dumps(players)))
            self._db.executemany(
                "INSERT OR REPLACE INTO player_games VALUES (?, ?, ?)",
                [(p["profile_id"], key, started_s) for p in players if p.get("profile_id")])

    def put_missing(self, key: str, status: str = "missing") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO games (key, status, analyzer, checked_at) VALUES (?, ?, ?, ?)",
                (key, status, ANALYZER_VERSION, time.time()))

    def local_games(self, profile_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(
                "SELECT g.* FROM games g JOIN player_games p ON p.key = g.key "
                "WHERE p.profile_id = ? AND g.key LIKE 'local:%' AND g.status = 'ok' "
                "AND g.analyzer = ? ORDER BY g.started DESC", (profile_id, ANALYZER_VERSION)).fetchall()

    def find_local(self, profile_id: int, started: datetime) -> sqlite3.Row | None:
        """A local recording of the same match, so we don't download what we already have."""
        lo = (started - timedelta(minutes=3)).isoformat()
        hi = (started + timedelta(minutes=3)).isoformat()
        with self._lock:
            return self._db.execute(
                "SELECT g.* FROM games g JOIN player_games p ON p.key = g.key "
                "WHERE p.profile_id = ? AND g.key LIKE 'local:%' AND g.status = 'ok' AND g.analyzer = ? "
                "AND g.started BETWEEN ? AND ?", (profile_id, ANALYZER_VERSION, lo, hi)).fetchone()

    def is_fresh(self, row: sqlite3.Row | None) -> bool:
        if row is None or row["analyzer"] != ANALYZER_VERSION:
            return False
        if row["status"] == "missing":
            return time.time() - row["checked_at"] < MISSING_RETRY_SECONDS
        return True


def game_from_row(row: sqlite3.Row) -> dict:
    return {"players": json.loads(row["players"]), "game_seconds": row["game_seconds"],
            "map_name": row["map_name"], "started": row["started"], "key": row["key"]}


class NotStandardStart(Exception):
    """Empire Wars, Death Match and other non-Dark-Age starts have no opening to read."""


def _analyze(raw: bytes) -> tuple[datetime | None, str | None, int, list[dict]]:
    record, strategies, game_seconds = analyze_recording(raw)
    if not record.standard_start:
        raise NotStandardStart
    return record.started, record.map_name, game_seconds, [strategy_dict(s) for s in strategies]


class ReplayService:
    def __init__(self, store: ReplayStore) -> None:
        self.store = store
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=True,
                                       headers={"User-Agent": config.USER_AGENT})
        self._downloads = asyncio.Semaphore(3)
        self._inflight: dict[str, asyncio.Task] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def match_game(self, match: dict, prefer_profile: int) -> dict | None:
        """An API match's analyzed replay: local copy, cache, or a fresh download."""
        key = f"api:{match['matchId']}"
        row = self.store.get(key)
        if self.store.is_fresh(row):
            return game_from_row(row) if row["status"] == "ok" else None
        started = datetime.fromisoformat(match["started"].replace("Z", "+00:00"))
        local = await asyncio.to_thread(self.store.find_local, prefer_profile, started) if config.USE_RECORDINGS else None
        if local:
            return game_from_row(local)
        # Several players' cards can ask for the same match at once; download it once.
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._download(match, prefer_profile))
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await task

    async def _download(self, match: dict, prefer_profile: int) -> dict | None:
        key = f"api:{match['matchId']}"
        # Replays are stored under whoever uploaded them, so try each player in turn.
        profiles = [p["profileId"] for t in match.get("teams", []) for p in t["players"] if p.get("profileId")]
        profiles.sort(key=lambda pid: pid != prefer_profile)
        for pid in profiles:
            async with self._downloads:
                try:
                    resp = await self._http.get(REPLAY_URL, params={"gameId": match["matchId"], "profileId": pid})
                except httpx.HTTPError as e:
                    log.warning("replay download failed for %s: %s", key, e)
                    return None  # network trouble: don't cache, try again next time
            if resp.status_code == 200 and resp.content[:2] == b"PK":
                try:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                        raw = z.read(z.namelist()[0])
                    started, map_name, seconds, players = await asyncio.to_thread(_analyze, raw)
                except NotStandardStart:
                    await asyncio.to_thread(self.store.put_missing, key, "skipped")
                    return None
                except Exception:  # noqa: BLE001 - corrupt or unparseable replay
                    log.exception("could not analyze replay %s", key)
                    break
                await asyncio.to_thread(self.store.put_ok, key, started, map_name, seconds, players)
                return game_from_row(await asyncio.to_thread(self.store.get, key))
        await asyncio.to_thread(self.store.put_missing, key)
        return None

    async def index_local(self, files: list[Path], skip: set[str]) -> int:
        """Analyze finished local recordings (yours, including lobby games the API lacks)."""
        added = 0
        for f in files:
            key = f"local:{f.name}"
            if f.name in skip or self.store.is_fresh(self.store.get(key)):
                continue
            try:
                raw = await asyncio.to_thread(f.read_bytes)
                started, map_name, seconds, players = await asyncio.to_thread(_analyze, raw)
            except NotStandardStart:
                await asyncio.to_thread(self.store.put_missing, key, "skipped")
                continue
            except Exception as e:  # noqa: BLE001 - partial or odd recordings
                log.debug("skipping %s: %s", f.name, e)
                await asyncio.to_thread(self.store.put_missing, key)
                continue
            await asyncio.to_thread(self.store.put_ok, key, started, map_name, seconds, players)
            added += 1
        return added
