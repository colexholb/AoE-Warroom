"""Local web app: serves the UI and streams the current match to it."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .aoe2companion import Aoe2CompanionClient, RateLimited
from .live import LiveService, list_recordings, recent_profile_ids
from .meta import counters as meta_counters
from .meta import civ_brief, civ_detail, civ_list, explore, map_info, options
from .replay_store import ReplayService, ReplayStore
from .record_header import parse_record

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = Path(__file__).parent / "static"
ICON_CDN = "https://backend.cdn.aoe2companion.com/public/aoe2/de/civilizations"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Aoe2CompanionClient()
    replays = ReplayService(ReplayStore())
    service = LiveService(client, replays)
    app.state.live = service
    await service.start()
    yield
    await service.stop()
    await client.close()
    await replays.close()


app = FastAPI(title="AoE Warroom", lifespan=lifespan)


@app.middleware("http")
async def revalidate_page_files(request, call_next):
    """Make browsers check for a newer app.js / styles.css on every load (a 304 when unchanged),
    so UI updates show up after a plain refresh instead of hiding behind a cached copy."""
    response = await call_next(request)
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/state")
async def get_state() -> dict:
    return app.state.live.state


@app.get("/api/events")
async def events() -> StreamingResponse:
    service: LiveService = app.state.live
    queue = service.subscribe()

    async def stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            service.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/recordings")
async def recordings() -> list[dict]:
    """Past games to review: your recordings, or your API match history in API-only mode."""
    service: LiveService = app.state.live
    if config.DETECT == "api":
        try:
            matches = await service.recent_api_games()
        except (httpx.HTTPError, RateLimited) as e:
            raise HTTPException(502, f"could not load your matches: {e}")
        return [{
            "key": f"api:{m['matchId']}",
            "started": m["started"],
            "map_name": m.get("mapName"),
            "players": sum(len(t.get("players") or []) for t in m.get("teams") or []),
            "live": not m.get("finished"),
        } for m in matches]

    def summarize() -> list[dict]:
        out = []
        for f in list_recordings(30):
            try:
                info = parse_record(f)
            except Exception:  # noqa: BLE001 - skip unreadable files
                continue
            out.append({
                "key": f.name,
                "started": info.started.isoformat() if info.started else None,
                "map_name": info.map_name,
                "players": len(info.players),
            })
        return out

    return await asyncio.to_thread(summarize)


class LoadRequest(BaseModel):
    key: str | None = None  # a key from /api/recordings; omitted = latest game


@app.post("/api/load")
async def load(req: LoadRequest) -> dict:
    service: LiveService = app.state.live
    if config.DETECT == "api":
        try:
            matches = await service.recent_api_games()
        except (httpx.HTTPError, RateLimited) as e:
            raise HTTPException(502, f"could not load your matches: {e}")
        target = matches[0] if matches and req.key is None else next(
            (m for m in matches if f"api:{m['matchId']}" == req.key), None)
        if target is None:
            raise HTTPException(404, "match not found")
        await service.load_api(target, live=not target.get("finished"))
        return {"ok": True}

    files = list_recordings(200)
    if not files:
        raise HTTPException(404, "no recordings found")
    # Only allow files from the savegame folders (friends on the LAN can hit this endpoint).
    target = files[0] if req.key is None else next((f for f in files if f.name == req.key), None)
    if target is None:
        raise HTTPException(404, "recording not found")
    await service.load(target, live=req.key is None and service.is_fresh(target))
    return {"ok": True}


@app.get("/api/profiles/search")
async def search_profiles(q: str) -> list[dict]:
    """Find your own profile by name, profile id or aoe2companion profile link. Profiles from
    your recent recordings come first, since that's almost certainly you among same-name players."""
    service: LiveService = app.state.live
    q = q.strip()
    id_match = re.fullmatch(r"(?:.*/profile/)?(\d{3,})/?", q)
    found: list[dict] = []
    try:
        if id_match:
            try:
                found.append(await service.client.profile(int(id_match.group(1))))
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (400, 404):  # 400/404: no such profile id
                    raise
        if len(q) >= 2 and "/" not in q:  # digits can be a name too ("805678789")
            ids = {p.get("profileId") for p in found}
            found += [p for p in await service.client.search_profiles(q) if p.get("profileId") not in ids]
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"aoe2companion answered {e.response.status_code}")
    except RateLimited as e:
        raise HTTPException(429, str(e))
    mine = await asyncio.to_thread(recent_profile_ids)
    results = [{
        "profile_id": p["profileId"],
        "name": p.get("name"),
        "country": p.get("country"),
        "clan": p.get("clan") or None,
        "games": int(p.get("games") or 0),
        "platform": p.get("platformName") or p.get("platform"),
        "avatar": (f"https://avatars.steamstatic.com/{p['avatarhash']}_medium.jpg"
                   if p.get("avatarhash") and p.get("platform") == "steam" else None),
        "in_recordings": p["profileId"] in mine,
    } for p in found if p.get("profileId")]
    return sorted(results, key=lambda r: not r["in_recordings"])  # stable: API order otherwise


class MeRequest(BaseModel):
    profile_id: int | None  # None forgets the pick and falls back to auto-detection


@app.post("/api/me")
async def set_me(req: MeRequest) -> dict:
    await app.state.live.set_me(req.profile_id)
    return {"ok": True}


@app.get("/overlay")
async def overlay() -> FileResponse:
    """OBS browser source: enemy scouting report on a transparent page."""
    return FileResponse(STATIC_DIR / "overlay.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Browsers and OBS ask for this path even when the page links its icon."""
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/civ-icons/{slug}.png")
async def civ_icon(slug: str) -> FileResponse:
    """Civ icons from aoe2companion's CDN, downloaded once and kept on disk."""
    if not re.fullmatch(r"[a-z]+", slug):
        raise HTTPException(404)
    icons = config.cache_dir() / "civ-icons"
    path = icons / f"{slug}.png"
    if not path.exists():
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(f"{ICON_CDN}/{slug}.png")
        if resp.status_code != 200:
            raise HTTPException(404)
        icons.mkdir(exist_ok=True)
        path.write_bytes(resp.content)
    return FileResponse(path, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/meta/options")
async def meta_options() -> dict:
    return options()


@app.get("/api/meta/civs")
async def meta_civs() -> list[dict]:
    return civ_list()


@app.get("/api/meta/civs/{slug}")
async def meta_civ(slug: str) -> dict:
    detail = civ_detail(slug)
    if detail is None:
        raise HTTPException(404, "civilization not found")
    return detail


@app.get("/api/meta/maps/{name}")
async def meta_map(name: str) -> dict:
    return map_info(name)


@app.get("/api/meta/explore")
async def meta_explore(
    tags: str = "",
    focus: str = "",
    units: str = "",
    techs: str = "",
) -> list[dict]:
    """AND-filter civs by playstyle tags + unit focus + must-have units/techs."""
    def split(s: str) -> list[str]:
        return [p.strip() for p in s.split(",") if p.strip()]
    return explore(split(tags), split(focus), split(units), split(techs))


@app.get("/api/meta/counter")
async def meta_counter(units: str = "", civs: str = "") -> dict:
    """Resolve counter answers for one or more enemy units.

    `units` is a CSV of enemy unit names (fuzzy-resolved against the
    counters.json keys). Empty input returns an empty payload without error
    so the client can use it as a heartbeat while the user has no enemy
    picked yet.
    """
    queries = [p.strip() for p in units.split(",") if p.strip()]
    slugs = [p.strip() for p in civs.split(",") if p.strip()]
    return meta_counters(queries, slugs)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
