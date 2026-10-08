"""In-memory spatial index for free drivers (replaces Redis GEOADD / GEOSEARCH).

The engine rebuilds the index from /state on every cycle, so nothing needs to
outlive a cycle and an external store adds no value.
"""
from __future__ import annotations

import math
from collections import defaultdict

from routing.graph import haversine_m

LatLng = tuple[float, float]
_KM_PER_DEG_LAT = 111.32


def haversine_km(a: LatLng, b: LatLng) -> float:
    return haversine_m(a, b) / 1000.0


class GridIndex:
    """Points bucketed into roughly cell_km x cell_km cells; radius search scans nearby cells only."""

    def __init__(self, cell_km: float = 1.0):
        self.cell_deg = cell_km / _KM_PER_DEG_LAT
        self._cells: dict[tuple[int, int], list[tuple[str, LatLng]]] = defaultdict(list)

    def _cell(self, p: LatLng) -> tuple[int, int]:
        return int(math.floor(p[0] / self.cell_deg)), int(math.floor(p[1] / self.cell_deg))

    def add(self, member: str, p: LatLng) -> None:
        self._cells[self._cell(p)].append((member, p))

    def within(self, center: LatLng, radius_km: float) -> list[tuple[str, float]]:
        """(member, distance_km) for every point within radius, nearest first."""
        reach_lat = math.ceil(radius_km / _KM_PER_DEG_LAT / self.cell_deg)
        cos_lat = max(math.cos(math.radians(center[0])), 0.01)
        reach_lng = math.ceil(radius_km / (_KM_PER_DEG_LAT * cos_lat) / self.cell_deg)
        ci, cj = self._cell(center)
        hits = []
        for i in range(ci - reach_lat, ci + reach_lat + 1):
            for j in range(cj - reach_lng, cj + reach_lng + 1):
                for member, p in self._cells.get((i, j), ()):
                    d = haversine_km(center, p)
                    if d <= radius_km:
                        hits.append((member, d))
        return sorted(hits, key=lambda h: h[1])
