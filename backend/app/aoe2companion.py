"""Thin async client for the public aoe2companion API, with a small in-memory cache."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import httpx

from . import config

log = logging.getLogger(__name__)

PROFILE_TTL = 5 * 60
SEARCH_TTL = 5 * 60
HISTORY_TTL = 5 * 60
# The API allows 16 requests per 10 seconds (X-RateLimit-* headers); stay a little under.
RATE_LIMIT = 14
RATE_WINDOW = 10.0
MAX_RETRIES = 4


class RateLimited(Exception):
    """aoe2companion kept answering 429 after retries."""

    def __str__(self) -> str:
        return "aoe2companion is rate limiting requests, try again in a minute"


class Aoe2CompanionClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=config.API_BASE,
            timeout=30,
            headers={"User-Agent": config.USER_AGENT},
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        self._sent: deque[float] = deque()
        self._gate = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    async def _wait_for_slot(self) -> None:
        async with self._gate:
            while True:
                now = time.monotonic()
                while self._sent and now - self._sent[0] > RATE_WINDOW:
                    self._sent.popleft()
                if len(self._sent) < RATE_LIMIT:
                    self._sent.append(now)
                    return
                await asyncio.sleep(RATE_WINDOW - (now - self._sent[0]) + 0.05)

    async def _get(self, key: str, ttl: float, path: str, params: dict | None = None) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        for attempt in range(MAX_RETRIES + 1):
            await self._wait_for_slot()
            resp = await self._http.get(path, params=params)
            if resp.status_code != 429:
                break
            wait = float(resp.headers.get("Retry-After") or 2 ** attempt)
            log.info("rate limited on %s, retrying in %.0fs", path, wait)
            await asyncio.sleep(wait)
        else:
            raise RateLimited
        resp.raise_for_status()
        data = resp.json()
        self._cache[key] = (time.monotonic(), data)
        return data

    async def profile(self, profile_id: int) -> dict:
        return await self._get(f"profile:{profile_id}", PROFILE_TTL, f"/profiles/{profile_id}")

    async def search_profiles(self, query: str) -> list[dict]:
        """Name search; aoe2companion returns up to 20, most games first."""
        data = await self._get(f"search:{query.lower()}", SEARCH_TTL, "/profiles", {"search": query})
        return data.get("profiles", [])

    async def matches(self, profile_id: int, count: int = config.HISTORY_SIZE) -> list[dict]:
        data = await self._get(
            f"matches:{profile_id}:{count}",
            HISTORY_TTL,
            "/matches",
            {"profile_ids": profile_id, "per_page": min(count, 300)},
        )
        return data.get("matches", [])
