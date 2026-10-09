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

from .aoe2companion import Aoe2CompanionClient
from .live import LiveService, list_recordings
from .record_header import parse_record

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = Path(__file__).parent / "static"
ICON_CACHE = Path(__file__).parent.parent / "cache" / "civ-icons"
ICON_CDN = "https://backend.cdn.aoe2companion.com/public/aoe2/de/civilizations"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Aoe2CompanionClient()
    service = LiveService(client)
    app.state.live = service
    await service.start()
    yield
    await service.stop()
    await client.close()


app = FastAPI(title="AoE Warroom", lifespan=lifespan)


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
    def summarize() -> list[dict]:
        out = []
        for f in list_recordings(30):
            try:
                info = parse_record(f)
            except Exception:  # noqa: BLE001 - skip unreadable files
                continue
            out.append({
                "file": f.name,
                "started": info.started.isoformat() if info.started else None,
                "map_name": info.map_name,
                "players": len(info.players),
            })
        return out

    return await asyncio.to_thread(summarize)


class LoadRequest(BaseModel):
    file: str | None = None  # file name from /api/recordings; omitted = latest


@app.post("/api/load")
async def load(req: LoadRequest) -> dict:
    files = list_recordings(200)
    if not files:
        raise HTTPException(404, "no recordings found")
    # Only allow files from the savegame folders (friends on the LAN can hit this endpoint).
    target = files[0] if req.file is None else next((f for f in files if f.name == req.file), None)
    if target is None:
        raise HTTPException(404, "recording not found")
    service: LiveService = app.state.live
    await service.load(target, live=req.file is None and service.is_fresh(target))
    return {"ok": True}


@app.get("/civ-icons/{slug}.png")
async def civ_icon(slug: str) -> FileResponse:
    """Civ icons from aoe2companion's CDN, downloaded once and kept on disk."""
    if not re.fullmatch(r"[a-z]+", slug):
        raise HTTPException(404)
    path = ICON_CACHE / f"{slug}.png"
    if not path.exists():
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(f"{ICON_CDN}/{slug}.png")
        if resp.status_code != 200:
            raise HTTPException(404)
        ICON_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return FileResponse(path, headers={"Cache-Control": "max-age=604800"})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
