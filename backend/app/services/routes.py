"""Trip distance / duration / road geometry, and the pickup-ETA provider for matching.

With road data (ROADS_PATH, default data/roads.pkl from routing.osm_import) routes follow the
real road network per vehicle. Without it, a straight-line estimate keeps tests simple.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from matching import EtaProvider, StraightLineEta
from matching.geo import LatLng, haversine_km
from routing import MultiVehicleRouter, VehicleType

log = logging.getLogger("uvicorn.error")   # shown in the uvicorn console

DETOUR_FACTOR = 1.4
STRAIGHT_LINE_SPEED_KMH = 30.0
MAX_ROUTE_POINTS = 1500


@dataclass(frozen=True)
class RouteEstimate:
    distance_m: int
    duration_s: int
    geometry: list[LatLng] = field(default_factory=list)


class RouteService:
    def __init__(self, router: MultiVehicleRouter | None = None):
        self.router = router
        # Matching ranks up to 10 nearby drivers per rider every 3 s, which the pure-Python router
        # can't do in time on a city graph, so pickup ETAs stay straight-line here. With GraphHopper
        # backends (milliseconds per route) this can become matching.RouterEta(router).
        self.pickup_eta: EtaProvider = StraightLineEta(STRAIGHT_LINE_SPEED_KMH, DETOUR_FACTOR)

    @property
    def has_roads(self) -> bool:
        return self.router is not None

    def estimate(self, origin: LatLng, dest: LatLng, vehicle: VehicleType,
                 depart_at: datetime | None = None) -> RouteEstimate | None:
        """None = no road route (outside the mapped area, or no legal way for this vehicle)."""
        depart_at = depart_at or datetime.now(timezone.utc)
        if self.router is None:
            km = haversine_km(origin, dest) * DETOUR_FACTOR
            return RouteEstimate(int(km * 1000), int(km / STRAIGHT_LINE_SPEED_KMH * 3600), [origin, dest])
        if vehicle not in self.router.services:
            return None
        result = self.router.route(vehicle, origin, dest, now=depart_at, depart_at=depart_at)
        if result is None:
            return None
        edges = self.router.services[vehicle].edges
        points: list[LatLng] = [origin]
        for seg in result.segments:
            geometry = edges[seg].geometry
            points.extend(geometry[1:] if points and geometry and points[-1] == geometry[0] else geometry)
        points.append(dest)
        return RouteEstimate(int(result.distance_m), int(result.eta_s), _thin(points))


def _thin(points: list[LatLng]) -> list[LatLng]:
    """Round to ~1 m and cap the size; the apps only draw it."""
    pts = [(round(lat, 5), round(lng, 5)) for lat, lng in points]
    deduped = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if len(deduped) <= MAX_ROUTE_POINTS:
        return deduped
    step = len(deduped) / MAX_ROUTE_POINTS
    return [deduped[int(i * step)] for i in range(MAX_ROUTE_POINTS)] + [deduped[-1]]


def load_route_service(roads_path: str | None) -> RouteService:
    if not roads_path:
        log.warning("no road data: routes are straight-line estimates (see docs/BACKEND.md, 'Road data')")
        return RouteService()
    from routing import IST, TimeBuckets
    from routing.osm_import import load

    started = time.monotonic()
    log.info("loading road data from %s ...", roads_path)
    router = MultiVehicleRouter.local(load(roads_path), buckets=TimeBuckets(IST))
    log.info("road data ready in %.0f s", time.monotonic() - started)
    return RouteService(router)
