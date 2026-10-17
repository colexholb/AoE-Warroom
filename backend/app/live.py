"""Finds new games (savegame folder and/or aoe2companion's websocket) and keeps the current
match + analysis up to date."""

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
from .ongoing import ongoing_events, record_from_match
from .playstyle import summarize
from .record_header import RecordInfo, parse_record
from .replay_store import ReplayService, game_from_row
from .stats import GameContext, analyze_player, team_summary

log = logging.getLogger(__name__)

RECORD_SUFFIX = ".aoe2record"
# Past games per player to pull strategy from, and how many recent matches to try for them.
REPLAY_SAMPLE = 10
REPLAY_CANDIDATES = 25
# How often to check that AoE2 is still recording games (one small API call).
RECORDING_CHECK_SECONDS = 5 * 60
# An API game that started this long after the newest recording's last write wasn't recorded.
UNRECORDED_GRACE = timedelta(minutes=2)
# A recording and an API match starting this close together (with shared players) are one game.
SAME_GAME_SECONDS = 180


def list_recordings(limit: int = 30) -> list[Path]:
    files = [f for d in config.savegame_dirs() for f in d.glob(f"*{RECORD_SUFFIX}")]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]


def recent_profile_ids(limit: int = 15) -> set[int]:
    """Everyone in your recent recordings: the profile picker ranks these first."""
    ids: set[int] = set()
    for f in list_recordings(limit):
        try:
            ids.update(p.profile_id for p in parse_record(f).players if p.profile_id)
        except Exception:
            continue
    return ids


def detect_my_profile() -> int | None:
    """You are in every recording on this PC, so the most common profile id is you."""
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
        self.me_source: str | None = None  # env | picked | detected
        self.state: dict = {"status": "waiting", "match": None, "players": [], "summary": None}
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._analysis: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._record: RecordInfo | None = None  # the loaded match, from a recording or the API
        self._api_match: dict | None = None  # set when the loaded match came from the API
        self._api_match_id: int | None = None  # its API id, also when the recording came first
        self._api_ended = False  # the API said it's over: don't revive it on a late file write
        self._api_task: asyncio.Task | None = None
        self._seen_recordings: set[str] = set()  # recordings of games the API had already found

    # ---- lifecycle -------------------------------------------------------------------------

    async def start(self) -> None:
        await self._resolve_me()
        dirs = config.savegame_dirs()
        self.state["watching"] = [str(d) for d in dirs]
        self.state["detect"] = config.DETECT
        log.info("watching %s as profile %s (%s), detecting games by %s",
                 dirs, self.me, self.me_source, config.DETECT)
        if config.DETECT == "api":
            # Last game from your API history (what a hosted version will do), then live games.
            self._tasks.append(asyncio.create_task(self._start_api()))
        else:
            recent = list_recordings(1)
            if recent:
                await self.load(recent[0], live=self.is_fresh(recent[0]))
            self._restart_api_watch()
        self._tasks.append(asyncio.create_task(self._check_recording()))
        if dirs:  # none in API mode
            self._tasks.append(asyncio.create_task(self._watch(dirs)))
            self._tasks.append(asyncio.create_task(self._index_local()))
        self._tasks.append(asyncio.create_task(self._liveness()))

    async def _start_api(self) -> None:
        # Before the websocket, so its snapshot of a running game wins over the last finished one.
        await self.load_last_api_game()
        self._restart_api_watch()

    async def stop(self) -> None:
        for task in [*self._tasks, self._analysis, self._api_task]:
            if task:
                task.cancel()

    # ---- who you are ----------------------------------------------------------------------

    async def _resolve_me(self) -> None:
        """AOE_PROFILE_ID, else the profile picked in the UI, else a guess from recordings."""
        picked = config.load_settings().get("profile_id")
        if config.MY_PROFILE_ID:
            self.me, self.me_source = config.MY_PROFILE_ID, "env"
        elif picked:
            self.me, self.me_source = int(picked), "picked"
        else:
            detected = await asyncio.to_thread(detect_my_profile)
            self.me, self.me_source = detected, "detected" if detected else None
        self.state["me"] = self.me
        self.state["me_source"] = self.me_source
        self.state["me_name"] = None
        if self.me:
            self._tasks.append(asyncio.create_task(self._fill_my_name()))

    async def _fill_my_name(self) -> None:
        try:
            profile = await self.client.profile(self.me)
        except Exception as e:  # noqa: BLE001 - the name is only cosmetic
            log.debug("could not fetch my profile: %s", e)
            return
        self.state["me_name"] = profile.get("name")
        self._publish()

    async def set_me(self, profile_id: int | None) -> None:
        """Remember the profile picked in the UI (None forgets it) and redo the current match
        so teams and advice flip to the right side."""
        config.save_settings(profile_id=profile_id)
        await self._resolve_me()
        match = self.state.get("match")
        live = self.state["status"] == "live"
        if config.DETECT == "api" and not live:
            await self.load_last_api_game()  # the new profile's last game, not the old one's
        elif self._api_match is not None:
            await self.load_api(self._api_match, live=live)
        elif match and match["path"] and Path(match["path"]).exists():
            await self.load(Path(match["path"]), live=live)
        else:
            self._publish()
        self._tasks.append(asyncio.create_task(self._check_recording()))
        self._restart_api_watch()  # the websocket listens for one profile's games

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

    async def load(self, path: Path, live: bool, record: RecordInfo | None = None) -> None:
        record = record or await self._parse_with_retry(path)
        if record is None:
            log.warning("could not read players from %s", path)
            return
        self._show(record, live, api_match=None)

    async def load_api(self, match: dict, live: bool = True) -> None:
        """A match from aoe2companion (websocket or `/matches`): no recording needed."""
        self._show(record_from_match(match), live, api_match=match)

    async def recent_api_games(self, limit: int = 10) -> list[dict]:
        """Your latest matches from the API, newest first. Same request (and cache entry) as your
        own card's history, so this usually costs no extra call."""
        if not self.me:
            return []
        return [m for m in await self.client.matches(self.me) if m.get("started")][:limit]

    async def load_last_api_game(self) -> None:
        """Show your last finished game; a running one arrives through the websocket."""
        try:
            matches = await self.recent_api_games()
        except Exception as e:  # noqa: BLE001 - the page just waits for the next game
            log.warning("could not fetch your last games: %s", e)
            return
        last = next((m for m in matches if m.get("finished")), None)
        if last:
            await self.load_api(last, live=False)

    def _show(self, record: RecordInfo, live: bool, api_match: dict | None) -> None:
        if self._analysis:
            self._analysis.cancel()
        self._record = record
        self._api_match = api_match
        self._api_match_id = api_match["matchId"] if api_match else None
        self._api_ended = False

        me = next((p for p in record.players if p.profile_id == self.me), None)
        my_team = me.team if me else None
        players = []
        for p in record.players:
            is_me = me is not None and p.number == me.number
            side = "me" if is_me else (
                "ally" if my_team is not None and p.team == my_team else "enemy")
            players.append({**p.__dict__, "is_me": is_me, "side": side, "analysis": None,
                            "loading": p.profile_id is not None, "playstyle": None, "comms": None})

        self.state.update({
            "status": "live" if live else "finished",
            "match": {
                # Identifies the match for the UI (e.g. to collapse cards when a new one starts).
                "key": Path(record.path).name if record.path else f"api:{self._api_match_id}",
                "source": "api" if api_match else "recording",
                "match_id": self._api_match_id,
                "file": Path(record.path).name if record.path else None,
                "path": record.path or None,
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
        _detect_comms(players, history, record.started)
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

        # Your own recordings cover lobby games the API never saw (not in API mode, like hosting).
        local_rows = await asyncio.to_thread(self.replays.store.local_games, pid) if config.USE_RECORDINGS else []
        for row in local_rows:
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
                if self.state["status"] != "live" and not self._api_ended:
                    self.state["status"] = "live"
                    self._publish()
                continue
            if self._api_match is not None and newest.name in self._seen_recordings:
                continue  # the recording of a game the API found first, still being written
            record = await self._parse_with_retry(newest)
            if record is None:
                log.warning("could not read players from %s", newest)
                continue
            if self._api_match is not None and self._is_current_game(record):
                log.info("%s is the game already loaded from the API", newest.name)
                self._seen_recordings.add(newest.name)
            else:
                log.info("new recording %s", newest.name)
                await self.load(newest, live=True, record=record)
            await self._check_recording()
            # The previous game just ended, so it can join the local index.
            self._tasks.append(asyncio.create_task(self._index_local()))

    async def _check_recording(self) -> None:
        """Warn when AoE2 isn't recording games, since then no game ever shows up here:
        no savegame folder, no recordings, or the API lists a game of yours that started after
        your newest recording was last written. API mode needs no recordings: never warn."""
        if not config.USE_RECORDINGS:
            return
        recordings = list_recordings(1)
        warning = None
        if not config.savegame_dirs():
            warning = {"kind": "no_folder"}
        elif not recordings:
            warning = {"kind": "no_recordings"}
        elif self.me:
            try:
                matches = await self.client.matches(self.me, count=5)
            except Exception as e:  # noqa: BLE001 - keep the previous verdict on API trouble
                log.debug("recording check failed: %s", e)
                return
            last_write = datetime.fromtimestamp(recordings[0].stat().st_mtime, timezone.utc)
            latest = max((datetime.fromisoformat(m["started"].replace("Z", "+00:00"))
                          for m in matches if m.get("started")), default=None)
            if latest and latest - last_write > UNRECORDED_GRACE:
                warning = {"kind": "not_recorded", "started": latest.isoformat()}
        if warning != self.state.get("recording_warning"):
            self.state["recording_warning"] = warning
            self._publish()

    async def _liveness(self) -> None:
        last_check = time.monotonic()
        while True:
            await asyncio.sleep(10)
            if time.monotonic() - last_check > RECORDING_CHECK_SECONDS:
                last_check = time.monotonic()
                await self._check_recording()
            match = self.state.get("match")
            # API matches end on the websocket's matchRemoved instead.
            if self.state["status"] == "live" and match and match["path"]:
                path = Path(match["path"])
                if not path.exists() or not self.is_fresh(path):
                    self._finish()

    def _finish(self) -> None:
        self.state["status"] = "finished"
        self._publish()

    # ---- live games from aoe2companion's websocket ----------------------------------------

    def _restart_api_watch(self) -> None:
        if self._api_task:
            self._api_task.cancel()
            self._api_task = None
        if config.DETECT != "folder" and self.me:
            self._api_task = asyncio.create_task(self._watch_api(self.me))

    async def _watch_api(self, profile_id: int) -> None:
        async for kind, data in ongoing_events(profile_id):
            try:
                await self._on_api_event(kind, data)
            except Exception:  # noqa: BLE001 - one bad event shouldn't stop detection
                log.exception("could not handle live game event %s", kind)

    async def _on_api_event(self, kind: str, data: dict) -> None:
        live = self.state["status"] == "live"
        if kind == "connected":
            # A game loaded from the API that ended while we were disconnected.
            if self._api_match is not None and live and self._api_match_id not in data["ongoing"]:
                self._finish()
        elif kind == "removed":
            if data["matchId"] == self._api_match_id and live:
                log.info("match %s ended", data["matchId"])
                self._api_ended = True
                self._finish()
        elif kind == "added":
            match_id = data["matchId"]
            if match_id == self._api_match_id:
                if not live and not self._api_ended:  # loaded from history, but it's running
                    self.state["status"] = "live"
                    self._publish()
                return  # already loaded (the connect snapshot repeats it)
            if self.me not in {p.get("profileId") for p in data.get("players") or []}:
                return
            record = record_from_match(data)
            if self._api_match is None and self._is_current_game(record):
                # The recording got here first: keep it, but let the API end the game.
                log.info("match %s is the game already loaded from its recording", match_id)
                self._api_match_id = self.state["match"]["match_id"] = match_id
                self.state["status"] = "live"
                self._publish()
                return
            await self.load_api(data)
            started = self._record.started if self._record else None
            delay = f"{(datetime.now(timezone.utc) - started).total_seconds():.0f}s" if started else "?"
            log.info("live match %s found by the API, %s after it started (mode: %s)",
                     match_id, delay, config.DETECT)

    def _is_current_game(self, record: RecordInfo) -> bool:
        """Whether `record` is the loaded match seen from the other source (recording vs API)."""
        current = self._record
        if current is None or current.started is None or record.started is None:
            return False
        ids = {p.profile_id for p in current.players if p.profile_id}
        close = abs((current.started - record.started).total_seconds()) < SAME_GAME_SECONDS
        return close and bool(ids & {p.profile_id for p in record.players if p.profile_id})


COMMS_SAMPLE = 10
COMMS_MIN_GAMES = 2


def _detect_comms(players: list[dict], history: dict[int, list[dict]], started: datetime | None) -> None:
    """Players in this lobby who were on the same team in 2+ of someone's last 10 games:
    likely a premade on voice comms."""
    cutoff = (started or datetime.now(timezone.utc)) - timedelta(minutes=2)
    in_lobby = {p["profile_id"]: p for p in players if p["profile_id"]}
    for p in players:
        matches = history.get(p["profile_id"])
        if matches is None:
            continue
        recent = [m for m in matches if m.get("started")
                  and datetime.fromisoformat(m["started"].replace("Z", "+00:00")) < cutoff][:COMMS_SAMPLE]
        together: Counter[int] = Counter()
        for m in recent:
            team_of = {pl.get("profileId"): t["teamId"] for t in m.get("teams", []) for pl in t["players"]}
            mine = team_of.get(p["profile_id"])
            for pid in in_lobby:
                if pid != p["profile_id"] and pid in team_of and team_of[pid] == mine:
                    together[pid] += 1
        p["comms"] = {
            "sample": len(recent),
            "with": [{"number": in_lobby[pid]["number"], "name": in_lobby[pid]["name"], "games": n,
                      "same_team_now": p["team"] is not None and in_lobby[pid]["team"] == p["team"]}
                     for pid, n in together.most_common() if n >= COMMS_MIN_GAMES],
        }


def _is_team_game(record: RecordInfo) -> bool:
    teams = Counter(p.team for p in record.players if p.team is not None)
    return any(n > 1 for n in teams.values())


def _format(record: RecordInfo) -> str:
    teams = Counter(p.team for p in record.players if p.team is not None)
    if len(teams) >= 2 and sum(teams.values()) == len(record.players):
        return "v".join(str(teams[t]) for t in sorted(teams))
    return f"FFA ({len(record.players)} players)"
