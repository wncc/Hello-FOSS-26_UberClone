"""Legal and access restrictions turned into rule statements.

  * road access (private / no / delivery / destination)  -> baseline priority rules
  * time-based closures (OSM *:conditional)              -> per-segment rules active in those buckets
  * restricted zones (OSM military areas, ops polygons)  -> InArea rules
  * toll avoidance (customer preference)                 -> per-request rule

Blocking uses priority 0 (Source.MAP / Source.OPS). Penalties stay > 0 so a trip
that must start or end inside a restricted place can still be routed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import (
    EdgeMeta, InArea, Op, RestrictedZone, RoadAccess, RoadAccessIs, SegmentIs, Source, Statement,
    Target, Toll, TollIs, ZoneKind,
)

# Ride-hailing cars are neither residents nor delivery vehicles.
ACCESS_PRIORITY: dict[RoadAccess, float] = {
    RoadAccess.NO: 0.0,
    RoadAccess.PRIVATE: 0.0,
    RoadAccess.DELIVERY: 0.0,
    RoadAccess.DESTINATION: 0.1,   # fine to drop someone off there, not to cut through
    RoadAccess.DISCOURAGED: 0.5,
}

ZONE_PRIORITY: dict[ZoneKind, float] = {
    ZoneKind.NO_ENTRY: 0.0,
    ZoneKind.AVOID: 0.1,
    ZoneKind.DESTINATION_ONLY: 0.1,
}

TOLL_AVOIDANCE_PRIORITY = 0.1  # still usable when there is no toll-free alternative


@dataclass(frozen=True)
class RouteOptions:
    avoid_tolls: bool = False


def access_statements() -> list[Statement]:
    """Part of the baseline (and the server's deploy/graphhopper/<vehicle>.json): always present."""
    return [
        Statement(Target.PRIORITY, RoadAccessIs(access), Op.MULTIPLY_BY, p, Source.BASELINE,
                  f"map.access.{access.value.lower()}")
        for access, p in ACCESS_PRIORITY.items()
    ]


def conditional_statements(edges: Iterable[EdgeMeta]) -> list[Statement]:
    return [
        Statement(Target.PRIORITY, SegmentIs(e.segment_id, e.road_class), Op.MULTIPLY_BY, 0.0, Source.MAP,
                  f"map.conditional.{e.segment_id}", reason="access:conditional",
                  active_buckets=e.no_access_buckets)
        for e in edges if e.no_access_buckets
    ]


def zone_statements(zones: Iterable[RestrictedZone]) -> list[Statement]:
    return [
        Statement(Target.PRIORITY, InArea(z.zone_id), Op.MULTIPLY_BY, ZONE_PRIORITY[z.kind],
                  Source.MAP if z.source == "osm" else Source.OPS, f"zone.{z.kind.value}.{z.zone_id}",
                  reason=z.name, active_buckets=z.active_buckets)
        for z in zones
    ]


def request_statements(options: RouteOptions | None) -> list[Statement]:
    if not options or not options.avoid_tolls:
        return []
    return [Statement(Target.PRIORITY, TollIs(Toll.ALL), Op.MULTIPLY_BY, TOLL_AVOIDANCE_PRIORITY,
                      Source.REQUEST, "request.avoid_tolls")]


def has_toll(edge: EdgeMeta) -> bool:
    """Edges are built per vehicle, so this is whether *this* vehicle pays here."""
    return edge.toll is Toll.ALL
