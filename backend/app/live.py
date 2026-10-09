"""Watches the savegame folder and keeps the current match + analysis up to date."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from watchfiles import Change, awatch

from . import config
from .aoe2companion import Aoe2CompanionClient
from .record_header import RecordInfo, parse_record
from .stats import GameContext, analyze_player, team_summary

log = logging.getLogger(__name__)

RECORD_SUFFIX = ".aoe2record"


def list_recordings(limit: int = 30) -> list[Path]:
    files = [f for d in config.savegame_dirs() for f in d.glob(f"*{RECORD_SUFFIX}")]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]


def detect_my_profile() -> int | None:
    """You are in every recording on this PC, so the most common profile id is you."""
    if config.MY_PROFILE_ID:
        return config.MY_PROFILE_ID
    counts: Counter[int] = Counter()
    files = list_recordings(15)
    for f in files:
        try:
            counts.update({p.profile_id for p in parse_record(f).players if p.profile_id})
        except Exception:
            continue
    if not counts:
        return None
    pid, seen = counts.most_common(1)[0]
    return pid if len(files) < 3 or seen >= len(files) * 0.6 else None


class LiveService:
    def __init__(self, client: Aoe2CompanionClient) -> None:
        self.client = client
        self.me: int | None = None
        self.state: dict = {"status": "waiting", "match": None, "players": [], "summary": None}
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._analysis: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []

    # ---- lifecycle -------------------------------------------------------------------------

    async def start(self) -> None:
        self.me = await asyncio.to_thread(detect_my_profile)
        dirs = config.savegame_dirs()
        self.state["watching"] = [str(d) for d in dirs]
        self.state["me"] = self.me
        log.info("watching %s as profile %s", dirs, self.me)
        recent = list_recordings(1)
        if recent:
            await self.load(recent[0], live=self.is_fresh(recent[0]))
        if dirs:
            self._tasks.append(asyncio.create_task(self._watch(dirs)))
        self._tasks.append(asyncio.create_task(self._liveness()))

    async def stop(self) -> None:
        for task in [*self._tasks, self._analysis]:
            if task:
                task.cancel()

    # ---- pub/sub ---------------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        q.put_nowait(self._snapshot())
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    def _snapshot(self) -> str:
        return json.dumps(self.state, default=str)

    def _publish(self) -> None:
        self.state["updated"] = datetime.now(timezone.utc).isoformat()
        payload = self._snapshot()
        for q in list(self._subscribers):
            if q.full():
                q.get_nowait()  # slow client: drop the oldest snapshot, they only need the latest
            q.put_nowait(payload)

    # ---- loading a match -------------------------------------------------------------------

    @staticmethod
    def is_fresh(path: Path) -> bool:
        return time.time() - path.stat().st_mtime < config.LIVE_TIMEOUT_SECONDS

    async def load(self, path: Path, live: bool) -> None:
        record = await self._parse_with_retry(path)
        if record is None:
            log.warning("could not read players from %s", path)
            return
        if self._analysis:
            self._analysis.cancel()

        me = next((p for p in record.players if p.profile_id == self.me), None)
        my_team = me.team if me else None
        players = []
        for p in record.players:
            is_me = me is not None and p.number == me.number
            side = "me" if is_me else (
                "ally" if my_team is not None and p.team == my_team else "enemy")
            players.append({**p.__dict__, "is_me": is_me, "side": side,
                            "analysis": None, "loading": p.profile_id is not None})

        self.state.update({
            "status": "live" if live else "finished",
            "match": {
                "file": Path(record.path).name,
                "path": record.path,
                "started": record.started.isoformat() if record.started else None,
                "map_name": record.map_name,
                "is_team_game": _is_team_game(record),
                "format": _format(record),
                "my_team": my_team,
            },
            "players": players,
            "summary": None,
        })
        self._publish()
        self._analysis = asyncio.create_task(self._analyze(record))

    async def _parse_with_retry(self, path: Path) -> RecordInfo | None:
        # A brand new recording may not have its header fully flushed yet.
        for _ in range(15):
            try:
                record = await asyncio.to_thread(parse_record, path)
                if record.players:
                    return record
            except Exception as e:  # noqa: BLE001 - partially written file
                log.debug("header not ready in %s: %s", path, e)
            await asyncio.sleep(1)
        return None

    async def _analyze(self, record: RecordInfo) -> None:
        is_team = _is_team_game(record)

        async def one(p: dict) -> None:
            ctx = GameContext(civ_slug=p["civ_slug"], civ_name=p["civ"], map_name=record.map_name,
                              is_team_game=is_team, started=record.started)
            try:
                profile, matches = await asyncio.gather(
                    self.client.profile(p["profile_id"]), self.client.matches(p["profile_id"]))
                p["analysis"] = analyze_player(p["profile_id"], profile, matches, ctx)
            except Exception as e:  # noqa: BLE001 - surface API failures on the card
                log.exception("analysis failed for %s", p["name"])
                p["analysis"] = {"error": str(e)}
            p["loading"] = False
            self._publish()

        players = self.state["players"]
        # Enemies first: they're what you want to see in the first seconds of a game.
        order = sorted((p for p in players if p["profile_id"]), key=lambda p: p["side"] != "enemy")
        await asyncio.gather(*(one(p) for p in order))
        self.state["summary"] = team_summary(players, self.state["match"]["my_team"])
        self._publish()

    # ---- background loops ------------------------------------------------------------------

    async def _watch(self, dirs: list[Path]) -> None:
        async for changes in awatch(*dirs, recursive=False):
            paths = {Path(p) for change, p in changes
                     if change in (Change.added, Change.modified) and p.endswith(RECORD_SUFFIX)}
            if not paths:
                continue
            newest = max(paths, key=lambda f: f.stat().st_mtime if f.exists() else 0)
            current = (self.state.get("match") or {}).get("path")
            if current and os.path.normcase(str(newest)) == os.path.normcase(current):
                if self.state["status"] != "live":
                    self.state["status"] = "live"
                    self._publish()
                continue
            log.info("new recording %s", newest.name)
            await self.load(newest, live=True)

    async def _liveness(self) -> None:
        while True:
            await asyncio.sleep(10)
            match = self.state.get("match")
            if self.state["status"] == "live" and match:
                path = Path(match["path"])
                if not path.exists() or not self.is_fresh(path):
                    self.state["status"] = "finished"
                    self._publish()


def _is_team_game(record: RecordInfo) -> bool:
    teams = Counter(p.team for p in record.players if p.team is not None)
    return any(n > 1 for n in teams.values())


def _format(record: RecordInfo) -> str:
    teams = Counter(p.team for p in record.players if p.team is not None)
    if len(teams) >= 2 and sum(teams.values()) == len(record.players):
        return "v".join(str(teams[t]) for t in sorted(teams))
    return f"FFA ({len(record.players)} players)"
