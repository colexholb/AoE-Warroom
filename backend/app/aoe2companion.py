"""Thin async client for the public aoe2companion API, with a small in-memory cache."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from . import config

PROFILE_TTL = 5 * 60
HISTORY_TTL = 5 * 60


class Aoe2CompanionClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=config.API_BASE,
            timeout=30,
            headers={"User-Agent": config.USER_AGENT},
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        # Be polite: never more than a few requests in flight.
        self._limit = asyncio.Semaphore(4)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, key: str, ttl: float, path: str, params: dict | None = None) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        async with self._limit:
            resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        data = resp.json()
        self._cache[key] = (time.monotonic(), data)
        return data

    async def profile(self, profile_id: int) -> dict:
        return await self._get(f"profile:{profile_id}", PROFILE_TTL, f"/profiles/{profile_id}")

    async def matches(self, profile_id: int, count: int = config.HISTORY_SIZE) -> list[dict]:
        data = await self._get(
            f"matches:{profile_id}:{count}",
            HISTORY_TTL,
            "/matches",
            {"profile_ids": profile_id, "per_page": min(count, 300)},
        )
        return data.get("matches", [])
