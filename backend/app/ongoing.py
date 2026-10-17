"""Live-game detection through aoe2companion's ongoing-matches websocket.

The websocket pushes `matchAdded` (the full match: map, settings, players with civ, color and
team) when a game you're in starts, and `matchRemoved` ~15-30 s after it ends. On connect it
sends the ongoing matches, or `[]` when there are none. That player info is what the loading
screen shows, so it stands in for the recording header (checked against 4 recordings: all 32
players matched on civ, color, team and player number).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

from websockets.asyncio.client import connect

from . import config
from .record_header import DARK_AGE_START, HeaderPlayer, RecordInfo

log = logging.getLogger(__name__)

WS_URL = "wss://socket.aoe2companion.com/listen"
RECONNECT_MIN_SECONDS = 5
RECONNECT_MAX_SECONDS = 120
# The websocket names starting ages; the REST API and recording headers use numbers.
STARTING_AGES = {"dark_age": DARK_AGE_START}


async def ongoing_events(profile_id: int) -> AsyncIterator[tuple[str, dict]]:
    """Yields ("added", match), ("removed", {"matchId": ...}) and, right after each (re)connect,
    ("connected", {"ongoing": [match ids]}) so a game that ended while disconnected can be closed.
    Reconnects forever with backoff."""
    url = f"{WS_URL}?handler=ongoing-matches&profile_ids={profile_id}"
    wait = RECONNECT_MIN_SECONDS
    while True:
        try:
            async with connect(url, user_agent_header=config.USER_AGENT, open_timeout=20) as ws:
                log.info("listening for live games of profile %s", profile_id)
                first = True
                async for raw in ws:
                    wait = RECONNECT_MIN_SECONDS
                    events = _parse(raw)
                    if first:
                        first = False
                        ongoing = [m["matchId"] for kind, m in events if kind == "added"]
                        yield "connected", {"ongoing": ongoing}
                    for event in events:
                        yield event
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - network trouble: reconnect
            log.warning("live game websocket dropped (%s); reconnecting in %ss", e, wait)
        await asyncio.sleep(wait)
        wait = min(wait * 2, RECONNECT_MAX_SECONDS)


def _parse(raw: str | bytes) -> list[tuple[str, dict]]:
    try:
        data = json.loads(raw)
    except ValueError:
        log.debug("non-JSON websocket message: %.200s", raw)
        return []
    out = []
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict):
            continue
        kind, match = item.get("type"), item.get("data")
        if kind is None and "matchId" in item:  # a bare match (format of the connect snapshot is unverified)
            kind, match = "matchAdded", item
        if kind == "matchAdded" and isinstance(match, dict) and match.get("matchId"):
            out.append(("added", match))
        elif kind == "matchRemoved" and isinstance(match, dict) and match.get("matchId"):
            out.append(("removed", match))
    return out


def record_from_match(match: dict) -> RecordInfo:
    """The API match in the shape of a recording header, so the analysis runs unchanged.
    Takes the websocket shape (flat `players`) and the REST `/matches` shape (players per team)."""
    flat = match.get("players") or [{"teamId": t.get("teamId"), **p}
                                    for t in match.get("teams") or [] for p in t.get("players") or []]
    players = []
    for i, p in enumerate(flat):
        profile_id = p.get("profileId") or None
        team = p.get("team", p.get("teamId"))
        color = p.get("color")
        slot = p.get("slot")
        players.append(HeaderPlayer(
            number=slot + 1 if isinstance(slot, int) else i + 1,  # matched the in-game number in all tests
            name=p.get("name") or "?",
            profile_id=profile_id,
            color_id=color - 1 if isinstance(color, int) else -1,  # API colors are 1-based
            team=team if isinstance(team, int) and team >= 1 else None,
            civ_id=-1,  # not in the API; nothing downstream needs it
            civ=p.get("civName") or p.get("civ") or "?",
            civ_slug=p.get("civ") or "",
            is_ai=profile_id is None,
        ))
    started = match.get("started")
    age = match.get("startingAge")
    return RecordInfo(
        path="",
        started=datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None,
        map_id=None,
        map_name=match.get("mapName"),
        starting_age=STARTING_AGES.get(age) if isinstance(age, str) else age,
        players=sorted(players, key=lambda p: p.number),
    )
