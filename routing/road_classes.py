"""Road hierarchy baseline: the preference order that must always exist.

Values mirror GraphHopper's `road_class` encoded value so the same names work
in local evaluation and in the serialized custom model.
"""
from enum import Enum


class RoadClass(str, Enum):
    MOTORWAY = "MOTORWAY"
    TRUNK = "TRUNK"
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    TERTIARY = "TERTIARY"
    UNCLASSIFIED = "UNCLASSIFIED"
    RESIDENTIAL = "RESIDENTIAL"
    LIVING_STREET = "LIVING_STREET"
    SERVICE = "SERVICE"
    TRACK = "TRACK"
    OTHER = "OTHER"


# Priority multipliers (1.0 = neutral, lower = penalized). Never > 1.0 so that
# A*/landmark heuristics stay admissible and telemetry can only penalize.
BASE_PRIORITY: dict[RoadClass, float] = {
    RoadClass.MOTORWAY: 1.0,
    RoadClass.TRUNK: 1.0,
    RoadClass.PRIMARY: 1.0,
    RoadClass.SECONDARY: 0.9,
    RoadClass.TERTIARY: 0.8,
    RoadClass.UNCLASSIFIED: 0.6,
    RoadClass.RESIDENTIAL: 0.5,
    RoadClass.LIVING_STREET: 0.2,
    RoadClass.SERVICE: 0.2,
    RoadClass.TRACK: 0.1,
    RoadClass.OTHER: 0.3,
}

# Every road is assumed to have the same expected speed until telemetry says
# otherwise. Road preference comes only from priority; slowness only from data.
# (Per-class / map speeds and an ETA prior are tracked in docs/issues/001.)
UNIFORM_SPEED_KMH = 30.0

MAIN_ROAD_CLASSES = frozenset({
    RoadClass.MOTORWAY, RoadClass.TRUNK, RoadClass.PRIMARY,
    RoadClass.SECONDARY, RoadClass.TERTIARY,
})


def priority_for(road_class: RoadClass, table: dict[RoadClass, float] | None = None) -> float:
    table = table or BASE_PRIORITY
    return table.get(road_class, table.get(RoadClass.OTHER, BASE_PRIORITY[RoadClass.OTHER]))


def base_rate(road_class: RoadClass, speed_kmh: float = UNIFORM_SPEED_KMH,
              table: dict[RoadClass, float] | None = None) -> float:
    """speed x priority: the denominator of the cost formula (higher = cheaper)."""
    return speed_kmh * priority_for(road_class, table)


# Soft telemetry may slow a main road down, but never below this margin over
# the residential baseline. Only HARD evidence may cross the line.
HIERARCHY_MARGIN = 1.1


def hierarchy_floor_rate(road_class: RoadClass, table: dict[RoadClass, float] | None = None) -> float:
    if road_class not in MAIN_ROAD_CLASSES:
        return 0.0
    return base_rate(RoadClass.RESIDENTIAL, table=table) * HIERARCHY_MARGIN
