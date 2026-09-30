"""Core data models: road metadata, telemetry events, rule statements, custom model."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Union

from .road_classes import RoadClass


# --------------------------------------------------------------------------- #
# Road metadata
# --------------------------------------------------------------------------- #

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
    speed_kmh: float  # free-flow / map speed (GraphHopper: car_average_speed)
    osm_way_id: int | None = None
    geometry: tuple[tuple[float, float], ...] = ()  # (lat, lon) points


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
    OPS = "ops"  # manual closures / incidents


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


Condition = Union[Always, RoadClassIs, SegmentIs]

# The only symbolic value we allow: the edge's own map speed.
EDGE_AVERAGE_SPEED = "car_average_speed"


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

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at


@dataclass
class CustomModel:
    speed: list[Statement] = field(default_factory=list)
    priority: list[Statement] = field(default_factory=list)
    # GraphHopper: extra seconds of cost per km. 0 keeps the pure Distance / (Speed x Priority) formula.
    distance_influence: float = 0.0

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


@dataclass(frozen=True)
class RoadHealth:
    segment_id: str
    speed_ratio: float      # shrunk observed / expected speed, 0..1
    avoidance_rate: float   # shrunk share of drivers avoiding it, 0..1
    health: float           # 0 (bad) .. 1 (healthy)
    speed_evidence: Evidence
    deviation_evidence: Evidence


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
