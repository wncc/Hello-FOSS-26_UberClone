"""Core data models: road metadata, telemetry events, rule statements, custom model."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Union

from .road_classes import UNIFORM_SPEED_KMH, RoadClass


# --------------------------------------------------------------------------- #
# Road metadata
# --------------------------------------------------------------------------- #

class RoadAccess(str, Enum):
    """Car access, named like GraphHopper's `road_access` encoded value."""
    DESIGNATED = "DESIGNATED"
    YES = "YES"
    DISCOURAGED = "DISCOURAGED"
    DESTINATION = "DESTINATION"   # only to reach something on this road (e.g. residents, customers)
    DELIVERY = "DELIVERY"
    PRIVATE = "PRIVATE"
    NO = "NO"


class Toll(str, Enum):
    """Named like GraphHopper's `toll` encoded value. HGV = toll for trucks only."""
    MISSING = "MISSING"
    NO = "NO"
    HGV = "HGV"
    ALL = "ALL"


class SpeedLimitSource(str, Enum):
    SIGN = "sign"                    # explicit maxspeed tag (posted limit or zone code)
    LEGAL_DEFAULT = "legal_default"  # national/state default for this kind of road


@dataclass(frozen=True)
class EdgeMeta:
    """A directed road segment.

    `segment_id` must be stable across map imports (e.g. "<osm_way_id>:<from_osm_node>:<to_osm_node>").
    GraphHopper's internal edge ids change on every import, so never persist those.
    """
    segment_id: str
    from_node: str
    to_node: str
    road_class: RoadClass
    distance_m: float
    # Expected driving speed = min(uniform speed, legal limit). Telemetry measures slowness against it.
    speed_kmh: float = UNIFORM_SPEED_KMH
    osm_way_id: int | None = None
    geometry: tuple[tuple[float, float], ...] = ()  # (lat, lon) points
    max_speed_kmh: float | None = None               # legal limit; None = unknown / no limit
    max_speed_source: SpeedLimitSource | None = None
    road_access: RoadAccess = RoadAccess.YES
    toll: Toll = Toll.MISSING
    # Time-of-week buckets in which cars may not use this road (from *:conditional tags).
    no_access_buckets: frozenset[int] | None = None


def expected_speed_kmh(max_speed_kmh: float | None, uniform_kmh: float = UNIFORM_SPEED_KMH) -> float:
    return uniform_kmh if max_speed_kmh is None else min(uniform_kmh, max_speed_kmh)


class ZoneKind(str, Enum):
    NO_ENTRY = "no_entry"                  # e.g. military area, closed campus: blocked
    AVOID = "avoid"                        # e.g. event area, congestion zone: strongly penalized
    DESTINATION_ONLY = "destination_only"  # e.g. airport forecourt, gated township


@dataclass(frozen=True)
class RestrictedZone:
    zone_id: str
    kind: ZoneKind
    polygon: tuple[tuple[float, float], ...]  # outer ring, (lat, lon)
    name: str = ""
    source: str = "ops"                         # "osm" or "ops"
    active_buckets: frozenset[int] | None = None  # None = always

    def contains(self, point: tuple[float, float]) -> bool:
        lat, lon = point
        inside = False
        ring = self.polygon
        for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:] + ring[:1]):
            if (lat1 > lat) != (lat2 > lat):
                cross = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
                if lon < cross:
                    inside = not inside
        return inside


# --------------------------------------------------------------------------- #
# Telemetry events (inputs produced by the trip / map-matching pipeline)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SpeedSample:
    segment_id: str
    driver_id: str
    trip_id: str
    speed_kmh: float
    observed_at: datetime


@dataclass(frozen=True)
class SegmentExposure:
    """The segment was on a driver's planned route and the driver reached its entry.

    followed=False means the driver deviated instead of taking it.
    """
    segment_id: str
    driver_id: str
    trip_id: str
    followed: bool
    observed_at: datetime


# --------------------------------------------------------------------------- #
# Rule statements (GraphHopper custom-model semantics)
# --------------------------------------------------------------------------- #

class Target(str, Enum):
    SPEED = "speed"
    PRIORITY = "priority"


class Op(str, Enum):
    MULTIPLY_BY = "multiply_by"
    LIMIT_TO = "limit_to"


class Source(str, Enum):
    BASELINE = "baseline"
    TELEMETRY_SPEED = "telemetry.speed"
    TELEMETRY_DEVIATION = "telemetry.deviation"
    TELEMETRY_TRAFFIC = "telemetry.traffic"  # time-of-week slowdown, chosen per request
    MAP = "map"  # restrictions from map data: access, conditional closures, OSM zones
    OPS = "ops"  # manual closures / incidents / ops-defined zones
    REQUEST = "request"  # per-trip customer preferences, e.g. avoid tolls


@dataclass(frozen=True)
class Always:
    pass


@dataclass(frozen=True)
class RoadClassIs:
    road_class: RoadClass


@dataclass(frozen=True)
class SegmentIs:
    segment_id: str
    # Narrows GraphHopper area matching to this class so a polygon drawn around
    # the segment does not also catch crossing roads of another class.
    road_class: RoadClass | None = None


@dataclass(frozen=True)
class RoadAccessIs:
    access: RoadAccess


@dataclass(frozen=True)
class TollIs:
    toll: Toll


@dataclass(frozen=True)
class InArea:
    zone_id: str


Condition = Union[Always, RoadClassIs, SegmentIs, RoadAccessIs, TollIs, InArea]

# Symbolic speed values, resolved per edge (GraphHopper encoded value names).
EDGE_AVERAGE_SPEED = "car_average_speed"   # map speed; unused while speeds are uniform
MAX_SPEED = "max_speed"                    # legal limit


@dataclass(frozen=True)
class Statement:
    target: Target
    condition: Condition
    op: Op
    value: float | str
    source: Source
    rule_id: str
    reason: str = ""
    expires_at: datetime | None = None
    # Time-of-week buckets this rule applies in (see time_buckets.py); None = always.
    active_buckets: frozenset[int] | None = None

    def is_active(self, now: datetime, bucket: int | None = None) -> bool:
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return self.active_buckets is None or (bucket is not None and bucket in self.active_buckets)


@dataclass
class CustomModel:
    speed: list[Statement] = field(default_factory=list)
    priority: list[Statement] = field(default_factory=list)
    # GraphHopper: extra seconds of cost per km. 0 keeps the pure Distance / (Speed x Priority) formula.
    distance_influence: float = 0.0
    # Polygons referenced by InArea conditions.
    areas: dict[str, RestrictedZone] = field(default_factory=dict)

    def statements(self) -> list[Statement]:
        return [*self.speed, *self.priority]


# --------------------------------------------------------------------------- #
# Aggregates / outputs
# --------------------------------------------------------------------------- #

class Evidence(str, Enum):
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


@dataclass(frozen=True)
class SegmentStats:
    segment_id: str
    speed_weight: float           # decay-weighted number of speed samples
    speed_drivers: int
    speed_days: int
    median_speed_kmh: float | None
    exposure_weight: float        # decay-weighted times the segment was offered
    deviation_weight: float       # decay-weighted times drivers avoided it
    deviating_drivers: int
    deviation_days: int
    # Exposures during the segment's peak traffic hours, kept apart from the ones
    # above so rush-hour avoidance is not mistaken for a permanently bad road.
    peak_exposure_weight: float = 0.0
    peak_deviation_weight: float = 0.0
    peak_deviating_drivers: int = 0
    peak_deviation_days: int = 0


@dataclass(frozen=True)
class RoadHealth:
    segment_id: str
    speed_ratio: float      # shrunk observed / expected speed, 0..1
    avoidance_rate: float   # shrunk share of drivers avoiding it, 0..1
    health: float           # 0 (bad) .. 1 (healthy)
    speed_evidence: Evidence
    deviation_evidence: Evidence
    peak_avoidance_rate: float | None = None
    peak_deviation_evidence: Evidence = Evidence.NONE
    # Strongly avoided and nobody drives it at all: likely a map error (gate,
    # missing turn restriction, closed road). Send to the map-fix queue.
    suspected_map_error: bool = False


@dataclass(frozen=True)
class EdgeEvaluation:
    segment_id: str
    speed_kmh: float
    priority: float
    applied_rules: tuple[str, ...]


@dataclass(frozen=True)
class RouteResult:
    segments: list[str]
    nodes: list[str]
    cost: float          # weighted cost (seconds / priority)
    distance_m: float
    eta_s: float         # pure travel time, priority excluded
    explanation: list[EdgeEvaluation]
    geometry: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon)
    toll_segments: list[str] = field(default_factory=list)
