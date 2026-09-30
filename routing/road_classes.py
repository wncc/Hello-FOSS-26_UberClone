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

# Fallback free-flow speeds (km/h) used when an edge carries no speed of its
# own. GraphHopper uses `car_average_speed` from OSM tags instead.
DEFAULT_SPEED_KMH: dict[RoadClass, float] = {
    RoadClass.MOTORWAY: 100.0,
    RoadClass.TRUNK: 80.0,
    RoadClass.PRIMARY: 60.0,
    RoadClass.SECONDARY: 50.0,
    RoadClass.TERTIARY: 40.0,
    RoadClass.UNCLASSIFIED: 30.0,
    RoadClass.RESIDENTIAL: 30.0,
    RoadClass.LIVING_STREET: 10.0,
    RoadClass.SERVICE: 15.0,
    RoadClass.TRACK: 10.0,
    RoadClass.OTHER: 20.0,
}

MAIN_ROAD_CLASSES = frozenset({
    RoadClass.MOTORWAY, RoadClass.TRUNK, RoadClass.PRIMARY,
    RoadClass.SECONDARY, RoadClass.TERTIARY,
})


def priority_for(road_class: RoadClass) -> float:
    return BASE_PRIORITY.get(road_class, BASE_PRIORITY[RoadClass.OTHER])


def default_speed_for(road_class: RoadClass) -> float:
    return DEFAULT_SPEED_KMH.get(road_class, DEFAULT_SPEED_KMH[RoadClass.OTHER])


def base_rate(road_class: RoadClass, speed_kmh: float | None = None) -> float:
    """speed x priority: the denominator of the cost formula (higher = cheaper)."""
    speed = speed_kmh if speed_kmh is not None else default_speed_for(road_class)
    return speed * priority_for(road_class)


# Soft telemetry may slow a main road down, but never below this margin over
# the residential baseline. Only HARD evidence may cross the line.
HIERARCHY_MARGIN = 1.1


def hierarchy_floor_rate(road_class: RoadClass) -> float:
    if road_class not in MAIN_ROAD_CLASSES:
        return 0.0
    return base_rate(RoadClass.RESIDENTIAL) * HIERARCHY_MARGIN
