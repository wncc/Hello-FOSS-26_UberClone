from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlaceResult:
    name: str
    address: str
    lat: float
    lng: float


class PlaceProvider(Protocol):
    async def search(
        self,
        query: str,
        near: tuple[float, float] | None = None,
    ) -> list[PlaceResult]:
        ...

import httpx


class PhotonProvider:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    async def search(
        self,
        query: str,
        near: tuple[float, float] | None = None,
    ) -> list[PlaceResult]:
        params = {"q": query, "limit": 8}

        if near is not None:
            lat, lng = near
            params["lat"] = lat
            params["lon"] = lng

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://photon.komoot.io/api/",
                params=params,
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for feature in data.get("features", []):
            properties = feature.get("properties", {})
            coordinates = feature.get("geometry", {}).get("coordinates", [])

            if len(coordinates) != 2:
                continue

            lng, lat = coordinates
            name = properties.get("name") or properties.get("street")
            if not name:
                continue

            address_parts = [
                properties.get("street"),
                properties.get("housenumber"),
                properties.get("city") or properties.get("locality"),
                properties.get("state"),
            ]
            address = ", ".join(dict.fromkeys(
                part.strip() for part in address_parts if isinstance(part, str) and part.strip()
            ))

            results.append(PlaceResult(
                name=name,
                address=address or name,
                lat=float(lat),
                lng=float(lng),
            ))

        return results[:8]

import asyncio
import time


class PlaceSearchService:
    def __init__(self, provider: PlaceProvider):
        self.provider = provider
        self.cache: dict[tuple[str, tuple[float, float] | None], tuple[float, list[PlaceResult]]] = {}
        self.cache_ttl = 300.0
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def search(
        self,
        query: str,
        near: tuple[float, float] | None = None,
    ) -> list[PlaceResult]:
        query = query.strip()
        if not query:
            return []

        key = (query.casefold(), near)
        now = time.monotonic()

        cached = self.cache.get(key)
        if cached and now - cached[0] < self.cache_ttl:
            return list(cached[1])

        async with self._lock:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and now - cached[0] < self.cache_ttl:
                return list(cached[1])

            wait = 1.0 - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)

            self._last_request = time.monotonic()
            results = await self.provider.search(query, near)
            self.cache[key] = (time.monotonic(), results)
            return list(results)