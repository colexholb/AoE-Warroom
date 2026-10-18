"""Player Search: assemble a Scout-style card for any aoe2companion profile, without needing
a live game. The page reuses the Scout player card verbatim; this module just produces the
payload and streams the slow pass (replay analysis) the same way live._playstyle does.

Streaming responses are owned by this module (one queue per request), not by the live
SSE channel, so a slow Player Search pass can never delay live-game updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx

from . import config
from .aoe2companion import Aoe2CompanionClient
from .playstyle import summarize
from .replay_store import ReplayService, game_from_row
from .stats import GameContext, all_leaderboards, analyze_player

log = logging.getLogger(__name__)

# Same constants live.py uses for Scout opponent replay sampling; keep these in one place
# so the two paths can't drift.
REPLAY_SAMPLE = 10
REPLAY_CANDIDATES = 25


async def scout_player(client: Aoe2CompanionClient, profile_id: int) -> dict:
    """Fetch the profile + last 300 matches, run `analyze_player` with an empty game
    context (no current civ/map/game), and return the assembled card payload for the
    Player Search tab. No replay pass here — that's streamed via `stream_playstyle`.

    Raises whatever the underlying client raises:
      - `httpx.HTTPStatusError` 404 for an unknown profile_id (caller → 404).
      - `RateLimited` from the aoe2companion client (caller → 429).
      - any other `httpx.HTTPError` (caller → 502).
    """
    profile, matches = await asyncio.gather(
        client.profile(profile_id), client.matches(profile_id))

    # Empty context: a searched player is not in any specific game, so civ/map/side are
    # unknown. analyze_player already handles None gracefully (current_civ / current_map
    # insights simply aren't generated).
    ctx = GameContext(civ_slug=None, civ_name=None, map_name=None,
                      is_team_game=False, started=None)
    analysis = analyze_player(profile_id, profile, matches, ctx)
    # The card expects Civ / color / team fields at the top level, not nested in
    # analysis. Fill them as None — Player Search has no game context.
    player = {
        "profile_id": profile_id,
        "name": profile.get("name") or f"Player {profile_id}",
        "country": profile.get("country"),
        "clan": profile.get("clan") or None,
        "platform": profile.get("platformName") or profile.get("platform"),
        "avatar": (f"https://avatars.steamstatic.com/{profile['avatarhash']}_medium.jpg"
                   if profile.get("avatarhash") and profile.get("platform") == "steam" else None),
        "civ": None,
        "civ_slug": None,
        "color": None,
        "team": None,
        "is_me": False,
        # `side` is a Scout concept (me / ally / enemy). Player Search has no game, so
        # we feed "enemy" — that gives the card the "Build:" counter label, the "Danger"
        # tag instead of "Strengths", and the "Exploit" tag instead of "Weaknesses".
        # The user is explicitly scouting this player; treating them as an opponent is
        # the right default.
        "side": "enemy",
    }

    return {
        "player": player,
        "ratings": all_leaderboards(profile),
        "analysis": analysis,
    }


def _started(m: dict) -> datetime | None:
    s = m.get("started")
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _is_team_match(team_counts: Counter, is_team_game: bool) -> bool:
    """True if `team_counts` looks like a team game iff `is_team_game`."""
    return any(n > 1 for n in team_counts.values()) == is_team_game


async def _replay_queue(
        replays: ReplayService, profile_id: int, matches: list[dict],
        cutoff: datetime) -> list[tuple[datetime, dict | None, dict | None]]:
    """Build the per-player replay queue, sorted newest-first and capped.

    Same logic as live._playstyle's queue construction (which we don't share because
    LiveService already holds all the per-call context). Returning the same shape
    guarantees both code paths feed `summarize()` with identical inputs.
    """
    results: dict[datetime, bool | None] = {}
    for m in matches:
        when = _started(m)
        if when is None:
            continue
        for t in m.get("teams", []):
            for pl in t.get("players", []):
                if pl.get("profileId") == profile_id:
                    results[when] = pl.get("won")
                    break

    queue: list[tuple[datetime, dict | None, dict | None]] = []  # (when, api match, local)
    for m in matches:
        when = _started(m)
        if when is None or when >= cutoff:
            continue
        teams = Counter(t["teamId"] for t in m.get("teams", []) for _ in t["players"])
        is_team = _is_team_match(teams, is_team_game=True)
        # Only normal Dark-Age starts have an opening worth reading (skip EW, DM, ...).
        dark_start = m.get("startingAge") == 2 and m.get("gameMode") == "random_map"
        if dark_start and is_team:
            queue.append((when, m, None))
    queue = queue[:REPLAY_CANDIDATES]

    if config.USE_RECORDINGS:
        local_rows = await asyncio.to_thread(replays.store.local_games, profile_id)
        for row in local_rows:
            game = game_from_row(row)
            when_str = game.get("started")
            if not when_str:
                continue
            when = datetime.fromisoformat(when_str)
            if when >= cutoff:
                continue
            # Same match as one already in the API list? Skip to avoid double counting.
            if any(abs((when - t).total_seconds()) < 180 for t in results):
                continue
            local_teams = Counter(pl["team"] for pl in game.get("players", []) if pl.get("team") is not None)
            if _is_team_match(local_teams, is_team_game=True):
                queue.append((when, None, game))
    queue.sort(key=lambda item: item[0], reverse=True)
    return queue


async def _build_playstyle(
        replays: ReplayService, profile_id: int, matches: list[dict],
        progress_cb) -> dict:
    """Run the slow pass for one player. Returns the same dict shape that
    `summarize()` produces — wrapped as `{"status": "done", ...}` only at the very end.

    `progress_cb` is `async (done, target)`, called with growing counters as replays
    are analyzed. The SSE handler uses this to stream loading snapshots.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    queue = await _replay_queue(replays, profile_id, matches, cutoff)
    target = min(REPLAY_SAMPLE, len(queue))
    await progress_cb(0, target)

    games: list[dict] = []
    for when, match, game in queue:
        if len(games) >= REPLAY_SAMPLE:
            break
        if game is None:
            game = await replays.match_game(match, profile_id)
        if not game:
            continue
        mine = next((s for s in game.get("players", []) if s.get("profile_id") == profile_id), None)
        if mine is None:
            continue
        # Win/loss attribution: use the same winning value the API returned.
        won = next(
            (pl.get("won") for t in (match or {}).get("teams", [])
             for pl in t.get("players", []) if pl.get("profileId") == profile_id),
            None)
        games.append({"strategy": mine, "won": won, "map_name": game["map_name"],
                      "game_seconds": game["game_seconds"] or 0})
        await progress_cb(len(games), target)

    # No `civ_slug` here (not in a game). `enemy=True` so the counsel is phrased as
    # "Danger:" / "Build:" — same default as the Player Search user intent.
    return {"status": "done", **summarize(games, current_civ=None, enemy=True)}


async def stream_playstyle(
        client: Aoe2CompanionClient, replays: ReplayService,
        profile_id: int) -> "AsyncIterator[str]":
    """Async generator yielding SSE-formatted payloads (one `data: …\\n\\n` per chunk)
    for the player's slow pass. Closes cleanly on cancellation (no leaked tasks).

    Wire shape: same as the live SSE — `{"status":"loading","done":N,"target":M}` lines
    then a final `{"status":"done", "summary": ...}` line with the same keys
    `summarize()` returns.
    """
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10)
    finished = asyncio.Event()
    error: dict[str, BaseException] = {}

    async def run() -> None:
        try:
            matches = await client.matches(profile_id)

            async def report(done: int, target: int) -> None:
                snapshot = {"status": "loading", "done": done, "target": target}
                await queue.put(f"data: {json.dumps(snapshot)}\n\n")

            result = await _build_playstyle(replays, profile_id, matches, report)
            await queue.put(f"data: {json.dumps(result)}\n\n")
        except BaseException as e:  # noqa: BLE001 - surface anything the frontend can show
            log.exception("playstyle pass failed for %s", profile_id)
            error["exc"] = e
            err = {"status": "error", "error": str(e)}
            await queue.put(f"data: {json.dumps(err)}\n\n")
        finally:
            finished.set()

    task = asyncio.create_task(run())
    try:
        while not finished.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield chunk
    finally:
        if not task.done():
            task.cancel()
        # Don't leak a half-cancelled pass.
        try:
            await task
        except (asyncio.CancelledError, BaseException):  # noqa: BLE001
            pass
        if "exc" in error and not finished.is_set():
            raise error["exc"]
