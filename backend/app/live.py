"""Watches the savegame folder and keeps the current match + analysis up to date."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from watchfiles import Change, awatch

from . import config
from .aoe2companion import Aoe2CompanionClient
from .playstyle import summarize
from .record_header import RecordInfo, parse_record
from .replay_store import ReplayService, game_from_row
from .stats import GameContext, analyze_player, team_summary

log = logging.getLogger(__name__)

RECORD_SUFFIX = ".aoe2record"
# Past games per player to pull strategy from, and how many recent matches to try for them.
REPLAY_SAMPLE = 10
REPLAY_CANDIDATES = 25


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
    def __init__(self, client: Aoe2CompanionClient, replays: ReplayService) -> None:
        self.client = client
        self.replays = replays
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
            self._tasks.append(asyncio.create_task(self._index_local()))
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
            players.append({**p.__dict__, "is_me": is_me, "side": side, "analysis": None,
                            "loading": p.profile_id is not None, "playstyle": None})

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
        history: dict[int, list[dict]] = {}

        async def one(p: dict) -> None:
            ctx = GameContext(civ_slug=p["civ_slug"], civ_name=p["civ"], map_name=record.map_name,
                              is_team_game=is_team, started=record.started)
            try:
                profile, matches = await asyncio.gather(
                    self.client.profile(p["profile_id"]), self.client.matches(p["profile_id"]))
                history[p["profile_id"]] = matches
                p["analysis"] = analyze_player(p["profile_id"], profile, matches, ctx)
            except httpx.HTTPStatusError as e:
                log.warning("history failed for %s: %s", p["name"], e)
                p["analysis"] = {"error": f"aoe2companion answered {e.response.status_code}"}
            except Exception as e:  # noqa: BLE001 - surface API failures on the card
                log.exception("analysis failed for %s", p["name"])
                p["analysis"] = {"error": str(e)}
            p["loading"] = False
            self._publish()

        players = self.state["players"]
        my_team = self.state["match"]["my_team"]
        # Enemies first: they're what you want to see in the first seconds of a game.
        order = sorted((p for p in players if p["profile_id"]), key=lambda p: p["side"] != "enemy")
        await asyncio.gather(*(one(p) for p in order))
        self.state["summary"] = team_summary(players, my_team)
        self._publish()

        # Second, slower pass: strategy from their recent replays.
        await asyncio.gather(*(self._playstyle(p, history.get(p["profile_id"], []), record, is_team)
                               for p in order))
        self.state["summary"] = team_summary(players, my_team)
        self._publish()

    async def _playstyle(self, p: dict, matches: list[dict], record: RecordInfo, is_team: bool) -> None:
        pid = p["profile_id"]
        # Never look at the game being played (or anything after it): past games only.
        cutoff = (record.started or datetime.now(timezone.utc)) - timedelta(minutes=2)
        current_file = Path(record.path).name

        def started(m: dict) -> datetime:
            return datetime.fromisoformat(m["started"].replace("Z", "+00:00"))

        def same_kind(teams: list[int]) -> bool:
            return any(n > 1 for n in Counter(teams).values()) == is_team

        dated = [m for m in matches if m.get("started")]
        results = {started(m): next((pl.get("won") for t in m.get("teams", []) for pl in t["players"]
                                     if pl.get("profileId") == pid), None) for m in dated}
        queue: list[tuple[datetime, dict | None, dict | None]] = []  # (when, api match, local game)
        for m in dated:
            teams = [t["teamId"] for t in m.get("teams", []) for _ in t["players"]]
            # Only normal Dark Age starts have an opening worth reading (skip EW, DM, ...).
            dark_start = m.get("startingAge") == 2 and m.get("gameMode") == "random_map"
            if started(m) < cutoff and same_kind(teams) and dark_start:
                queue.append((started(m), m, None))
        queue = queue[:REPLAY_CANDIDATES]

        # Your own recordings cover lobby games the API never saw.
        for row in await asyncio.to_thread(self.replays.store.local_games, pid):
            game = game_from_row(row)
            when = datetime.fromisoformat(game["started"]) if game["started"] else None
            if when is None or when >= cutoff or row["key"] == f"local:{current_file}":
                continue
            if any(abs((when - t).total_seconds()) < 180 for t in results):
                continue  # same match as an API one, which finds this local copy itself
            if same_kind([pl["team"] for pl in game["players"] if pl["team"] is not None]):
                queue.append((when, None, game))
        queue.sort(key=lambda item: item[0], reverse=True)

        games: list[dict] = []
        p["playstyle"] = {"status": "loading", "done": 0, "target": min(REPLAY_SAMPLE, len(queue))}
        self._publish()
        for when, match, game in queue:
            if len(games) >= REPLAY_SAMPLE:
                break
            if game is None:
                game = await self.replays.match_game(match, pid)
            mine = next((s for s in (game or {}).get("players", []) if s.get("profile_id") == pid), None)
            if mine is None:
                continue
            games.append({"strategy": mine, "won": results.get(when), "map_name": game["map_name"],
                          "game_seconds": game["game_seconds"] or 0})
            p["playstyle"]["done"] = len(games)
            self._publish()
        p["playstyle"] = {"status": "done", **summarize(games, p["civ_slug"], enemy=p["side"] == "enemy")}
        self._publish()

    async def _index_local(self) -> None:
        """Analyze finished recordings in the background so they can be reused for scouting."""
        files = list_recordings(1000)
        current = Path((self.state.get("match") or {}).get("path") or "").name
        # Skip anything still being written: that's a game in progress.
        skip = {f.name for f in files if self.is_fresh(f)} | {current}
        added = await self.replays.index_local(files, skip)
        if added:
            log.info("indexed %d local recordings", added)

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
            # The previous game just ended, so it can join the local index.
            self._tasks.append(asyncio.create_task(self._index_local()))

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
