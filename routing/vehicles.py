"""Vehicle profiles: car, auto rickshaw, bike (motorcycle / scooter).

Each profile carries the legal speed limits for its category, which OSM
access and toll tags apply to it, its road preferences, its turn costs, and
the fixed time lost at point features (signals, toll booths, level crossings).

Legal limits: MoRTH S.O. 1522(E), 6 April 2018 (km/h):
                    expressway   4+ lane divided   municipal   other
    M1 car             120            100              70         70
    motorcycle          80*            80              60         60
    three-wheeler     not permitted    50              50         50
    (* where permitted; several expressways ban two-wheelers, tagged motorcycle=no in OSM)

Values marked ASSUMPTION are starting points to be replaced by learned values.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .road_classes import BASE_PRIORITY, UNIFORM_SPEED_KMH, RoadClass


class VehicleType(str, Enum):
    CAR = "car"
    AUTO = "auto_rickshaw"
    BIKE = "bike"


@dataclass(frozen=True)
class LegalSpeedDefaults:
    """Limits that apply where no sign is mapped.

    `city_cap_kmh` applies a city's own notification (usually lower than the
    national maximum) to every non-expressway default. Signs are never capped by it.
    """
    country: str
    motorway: float | None          # None = vehicle category not permitted on expressways
    divided_highway: float
    other: float
    zone_codes: dict[str, float] = field(default_factory=dict)  # "<CC>:<kind>" maxspeed values
    city_cap_kmh: float | None = None

    @property
    def motorway_permitted(self) -> bool:
        return self.motorway is not None

    def default_for(self, road_class: RoadClass, divided: bool) -> float:
        if road_class is RoadClass.MOTORWAY and self.motorway is not None:
            return self.motorway
        limit = self.divided_highway if divided and road_class in (RoadClass.TRUNK, RoadClass.PRIMARY) else self.other
        return min(limit, self.city_cap_kmh) if self.city_cap_kmh else limit

    def legal_max(self, road_class: RoadClass, divided: bool) -> float:
        """The category maximum for this kind of road, ignoring any city cap."""
        return replace(self, city_cap_kmh=None).default_for(road_class, divided)


INDIA_M1 = LegalSpeedDefaults(
    country="IN", motorway=120.0, divided_highway=100.0, other=70.0,
    zone_codes={"motorway": 120.0, "trunk": 100.0, "urban": 70.0, "rural": 70.0},
)
INDIA_MOTORCYCLE = LegalSpeedDefaults(
    country="IN", motorway=80.0, divided_highway=80.0, other=60.0,
    zone_codes={"motorway": 80.0, "trunk": 80.0, "urban": 60.0, "rural": 60.0},
)
INDIA_THREE_WHEELER = LegalSpeedDefaults(
    country="IN", motorway=None, divided_highway=50.0, other=50.0,
    zone_codes={"trunk": 50.0, "urban": 50.0, "rural": 50.0},
)


@dataclass(frozen=True)
class TurnCosts:
    """Seconds lost per manoeuvre, on top of any signal wait. India drives on the left,
    so the right turn crosses oncoming traffic and the left turn is the easy one."""
    straight: float
    near_side: float     # left turn in India
    far_side: float      # right turn in India, across oncoming traffic
    u_turn: float


@dataclass(frozen=True)
class VehicleProfile:
    vehicle: VehicleType
    osm_keys: tuple[str, ...]          # most specific OSM access/toll/restriction keys, e.g. ("motorcar",)
    legal: LegalSpeedDefaults
    # Posted signs apply to everyone, but a vehicle may not exceed its category maximum
    # (an auto rickshaw stays at 50 on an 80 km/h highway). Cars follow signs as posted.
    cap_signs_at_category: bool
    pays_toll: bool                    # when only a generic `toll=yes` is mapped
    toll_key: str | None               # vehicle-specific toll tag, e.g. toll:motorcar
    priority: dict[RoadClass, float]
    turns: TurnCosts
    point_delay_s: dict[str, float]
    uniform_speed_kmh: float = UNIFORM_SPEED_KMH


# ASSUMPTION: average waits. Signal cycles in Indian cities are often 90-180 s; a
# random arrival waits about half the red phase. FASTag toll lanes take ~10-30 s;
# two-wheelers use the exempt side lane. Manned railway crossings close for minutes
# but are open most of the time.
_SIGNAL_S, _LEVEL_CROSSING_S = 30.0, 60.0

CAR = VehicleProfile(
    vehicle=VehicleType.CAR, osm_keys=("motorcar",), legal=INDIA_M1, cap_signs_at_category=False,
    pays_toll=True, toll_key="motorcar", priority=dict(BASE_PRIORITY),
    turns=TurnCosts(straight=0.0, near_side=3.0, far_side=10.0, u_turn=25.0),
    point_delay_s={"traffic_signals": _SIGNAL_S, "toll_booth": 20.0, "level_crossing": _LEVEL_CROSSING_S},
)

# Two-wheelers filter through traffic and small lanes, so minor roads are penalized less.
BIKE = VehicleProfile(
    vehicle=VehicleType.BIKE, osm_keys=("motorcycle",), legal=INDIA_MOTORCYCLE, cap_signs_at_category=True,
    pays_toll=False, toll_key="motorcycle",  # two-wheelers are exempt at national-highway fee plazas
    priority={**BASE_PRIORITY, RoadClass.SECONDARY: 0.95, RoadClass.TERTIARY: 0.9,
              RoadClass.UNCLASSIFIED: 0.8, RoadClass.RESIDENTIAL: 0.7, RoadClass.LIVING_STREET: 0.4,
              RoadClass.SERVICE: 0.5, RoadClass.TRACK: 0.2},
    turns=TurnCosts(straight=0.0, near_side=2.0, far_side=6.0, u_turn=12.0),
    point_delay_s={"traffic_signals": _SIGNAL_S, "toll_booth": 5.0, "level_crossing": _LEVEL_CROSSING_S},
)

# Auto rickshaws: narrow and slow; follow the stricter of the car and motorcycle rules
# because OSM has no widely used auto-rickshaw access key.
AUTO = VehicleProfile(
    vehicle=VehicleType.AUTO, osm_keys=("motorcar", "motorcycle"), legal=INDIA_THREE_WHEELER,
    cap_signs_at_category=True,
    pays_toll=False, toll_key=None,  # ASSUMPTION: verify per plaza; state-run tolls may charge three-wheelers
    priority={**BASE_PRIORITY, RoadClass.UNCLASSIFIED: 0.7, RoadClass.RESIDENTIAL: 0.6,
              RoadClass.LIVING_STREET: 0.3, RoadClass.SERVICE: 0.3},
    turns=TurnCosts(straight=0.0, near_side=2.0, far_side=8.0, u_turn=18.0),
    point_delay_s={"traffic_signals": _SIGNAL_S, "toll_booth": 10.0, "level_crossing": _LEVEL_CROSSING_S},
)

PROFILES: dict[VehicleType, VehicleProfile] = {p.vehicle: p for p in (CAR, BIKE, AUTO)}

# ASSUMPTION: a speed breaker keeps drivers slightly below the road's expected speed.
SPEED_BREAKER_FACTOR = 0.9
