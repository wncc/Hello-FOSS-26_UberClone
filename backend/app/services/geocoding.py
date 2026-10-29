
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Protocol

import httpx


class Geocoder(Protocol):
    async def reverse(self, lat: float, lng: float) -> str | None:
        """Return a short address, or None if lookup fails."""
        ...

    async def close(self) -> None:
        """Release provider resources."""
        ...


class ReverseGeocoder:
    """Nominatim reverse geocoder with a small in-memory cache."""

    def __init__(
        self,
        timeout_seconds: float = 1.5,
        cache_size: int = 1000,
        user_agent: str = (
            "HelloFOSS-UberClone/1.0 "
            "(https://github.com/wncc/Hello-FOSS-26_UberClone)"
        ),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache_size = cache_size
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )
        self._cache: OrderedDict[tuple[float, float], str | None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def reverse(self, lat: float, lng: float) -> str | None:
        key = (round(lat, 5), round(lng, 5))

        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        # Nominatim's public service requires at most one request per second.
        async with self._lock:
            wait = 1.0 - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

        try:
            response = await self._client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "jsonv2",
                    "lat": lat,
                    "lon": lng,
                    "zoom": 18,
                    "addressdetails": 1,
                },
            )
            response.raise_for_status()
            data = response.json()
            address = data.get("address", {})
            parts = [
                address.get("road"),
                address.get("neighbourhood"),
                address.get("suburb"),
                address.get("city") or address.get("town") or address.get("village"),
            ]
            result = ", ".join(dict.fromkeys(p for p in parts if p)) or None
        except (httpx.HTTPError, ValueError, TypeError):
            result = None

        async with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

        return result

    async def close(self) -> None:
        await self._client.aclose()
