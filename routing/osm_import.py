"""Build road metadata from OpenStreetMap: speed limits, access, tolls, time-based closures, zones.

Input: an .osm or .osm.pbf extract of the operating city, e.g. from
https://download.geofabrik.de/asia/india.html (clip to the city with `osmium extract`).
The segment ids ("<way>:<from node>:<to node>") match what GraphHopper imports from
the same file, so telemetry keyed on them lines up with routing.

    python -m routing.osm_import city.osm.pbf --out roads.json [--city-cap 50]

Tag parsing is pure functions (tested without a file); the reader needs `pip install osmium`.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from typing import Iterable

from .graph import haversine_m
from .models import (
    EdgeMeta, RestrictedZone, RoadAccess, SpeedLimitSource, Toll, ZoneKind, expected_speed_kmh,
)
from .road_classes import UNIFORM_SPEED_KMH, RoadClass
from .time_buckets import HOURS, SATURDAY, SUNDAY, WEEKDAY

HIGHWAY_CLASS: dict[str, RoadClass] = {
    "motorway": RoadClass.MOTORWAY, "motorway_link": RoadClass.MOTORWAY,
    "trunk": RoadClass.TRUNK, "trunk_link": RoadClass.TRUNK,
    "primary": RoadClass.PRIMARY, "primary_link": RoadClass.PRIMARY,
    "secondary": RoadClass.SECONDARY, "secondary_link": RoadClass.SECONDARY,
    "tertiary": RoadClass.TERTIARY, "tertiary_link": RoadClass.TERTIARY,
    "unclassified": RoadClass.UNCLASSIFIED,
    "residential": RoadClass.RESIDENTIAL,
    "living_street": RoadClass.LIVING_STREET,
    "service": RoadClass.SERVICE,
    "track": RoadClass.TRACK,
    "road": RoadClass.OTHER,
}

MPH_TO_KMH = 1.609344
WALK_KMH = 7.0


# --------------------------------------------------------------------------- #
# Speed limits
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LegalSpeedDefaults:
    """Limits that apply where no sign is mapped.

    `city_cap_kmh` applies a city's own notification (usually lower than the
    national maximum) to every non-expressway default. Signs are never capped.
    """
    country: str
    motorway: float
    divided_highway: float
    other: float
    zone_codes: dict[str, float] = field(default_factory=dict)  # "<CC>:<kind>" maxspeed values
    city_cap_kmh: float | None = None

    def default_for(self, road_class: RoadClass, divided: bool) -> float:
        if road_class is RoadClass.MOTORWAY:
            return self.motorway
        limit = self.divided_highway if divided and road_class in (RoadClass.TRUNK, RoadClass.PRIMARY) else self.other
        return min(limit, self.city_cap_kmh) if self.city_cap_kmh else limit


# MoRTH S.O. 1522(E), 6 April 2018, category M1 (cars with <= 8 passenger seats):
# expressways 120, four-lane-or-more divided highways 100, municipal and other roads 70.
# Some secondary sources quote 60 for urban roads; confirm against the gazette and set
# city_cap_kmh from the city traffic police notification (often 40-60 km/h).
INDIA_M1 = LegalSpeedDefaults(
    country="IN", motorway=120.0, divided_highway=100.0, other=70.0,
    zone_codes={"motorway": 120.0, "trunk": 100.0, "urban": 70.0, "rural": 70.0},
)

_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?$")
_ZONE = re.compile(r"^([A-Z]{2}):([a-z_]+?)(\d+)?$")


def parse_maxspeed(value: str, legal: LegalSpeedDefaults = INDIA_M1) -> float | None:
    """km/h, or None for 'no limit' / unknown. Multiple values ('50;60') -> the lowest."""
    speeds = [s for s in (_parse_one_maxspeed(v.strip(), legal) for v in value.split(";")) if s]
    return min(speeds) if speeds else None


def _parse_one_maxspeed(v: str, legal: LegalSpeedDefaults) -> float | None:
    if v == "walk":
        return WALK_KMH
    m = _NUMBER.match(v)
    if m:
        kmh = float(m.group(1)) * (MPH_TO_KMH if m.group(2) == "mph" else 1.0)
        return kmh if kmh > 0 else None
    m = _ZONE.match(v)
    if m:
        kind, number = m.group(2), m.group(3)
        if kind == "zone" and number:
            return float(number)
        return legal.zone_codes.get(kind) if m.group(1) == legal.country else None
    return None  # "none", "signals", "variable", unparseable


def maxspeed_for(tags: dict[str, str], direction: str, road_class: RoadClass, divided: bool,
                 legal: LegalSpeedDefaults = INDIA_M1) -> tuple[float | None, SpeedLimitSource]:
    for key in (f"maxspeed:{direction}", "maxspeed"):
        if key in tags:
            if tags[key] == "none":
                return None, SpeedLimitSource.SIGN
            kmh = parse_maxspeed(tags[key], legal)
            if kmh is not None:
                return kmh, SpeedLimitSource.SIGN
    return legal.default_for(road_class, divided), SpeedLimitSource.LEGAL_DEFAULT


def is_divided(tags: dict[str, str]) -> bool:
    """Divided carriageways are mapped as two one-way ways, or tagged explicitly."""
    if tags.get("dual_carriageway") == "yes" or tags.get("oneway") in ("yes", "true", "1"):
        return True
    try:
        return int(tags.get("lanes", "0")) >= 4
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Access, oneway, toll
# --------------------------------------------------------------------------- #

ACCESS_KEYS = ("access", "vehicle", "motor_vehicle", "motorcar")   # least -> most specific
ACCESS_VALUES: dict[str, RoadAccess] = {
    "yes": RoadAccess.YES, "permissive": RoadAccess.YES,
    "designated": RoadAccess.DESIGNATED,
    "destination": RoadAccess.DESTINATION, "customers": RoadAccess.DESTINATION,
    "delivery": RoadAccess.DELIVERY,
    "private": RoadAccess.PRIVATE, "permit": RoadAccess.PRIVATE,
    "discouraged": RoadAccess.DISCOURAGED,
    "no": RoadAccess.NO, "agricultural": RoadAccess.NO, "forestry": RoadAccess.NO,
    "military": RoadAccess.NO, "emergency": RoadAccess.NO, "restricted": RoadAccess.NO,
}
BLOCKING_ACCESS = {"no", "private", "delivery", "agricultural", "forestry", "military", "emergency", "restricted"}


def parse_access(tags: dict[str, str]) -> RoadAccess:
    for key in reversed(ACCESS_KEYS):
        access = ACCESS_VALUES.get(tags.get(key, ""))
        if access is not None:
            return access
    return RoadAccess.YES


def parse_toll(tags: dict[str, str]) -> Toll:
    car = tags.get("toll:motorcar") or tags.get("toll")
    if car in ("yes", "no"):
        return Toll.ALL if car == "yes" else Toll.NO
    if tags.get("toll:hgv") == "yes":
        return Toll.HGV
    return Toll.MISSING


def parse_oneway(tags: dict[str, str], highway: str) -> int:
    """1 = forward only, -1 = backward only, 0 = both directions."""
    v = tags.get("oneway")
    if v in ("yes", "true", "1"):
        return 1
    if v == "-1":
        return -1
    if v == "no":
        return 0
    return 1 if highway in ("motorway", "motorway_link") or tags.get("junction") == "roundabout" else 0


# --------------------------------------------------------------------------- #
# Time-based closures (*:conditional) -> time buckets
# --------------------------------------------------------------------------- #

CONDITIONAL_KEYS = ("motorcar:conditional", "motor_vehicle:conditional", "vehicle:conditional", "access:conditional")
_DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_DAY_TOKEN = re.compile(r"^(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$")


class UnsupportedCondition(ValueError):
    pass


def parse_conditional(tags: dict[str, str]) -> tuple[frozenset[int] | None, bool]:
    """(buckets in which cars are blocked, parsed_ok). Most specific key wins.

    Supports "no @ (Mo-Fr 07:00-11:00,17:00-21:00; Sa 10:00-14:00)". Anything
    else (dates, holidays, weight/wet conditions) is reported as not parsed and
    ignored, rather than guessed.
    """
    key = next((k for k in CONDITIONAL_KEYS if k in tags), None)
    if key is None:
        return None, True
    buckets: set[int] = set()
    try:
        for restriction, condition in _split_conditional(tags[key]):
            if restriction in BLOCKING_ACCESS:
                buckets |= _opening_hours_buckets(condition)
    except UnsupportedCondition:
        return None, False
    return (frozenset(buckets) or None), True


def _split_conditional(value: str) -> Iterable[tuple[str, str]]:
    parts, depth, current = [], 0, ""
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == ";" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    for part in filter(str.strip, parts):
        if "@" not in part:
            raise UnsupportedCondition(part)
        restriction, condition = part.split("@", 1)
        yield restriction.strip(), condition.strip().strip("()").strip()


def _opening_hours_buckets(spec: str) -> set[int]:
    buckets: set[int] = set()
    for rule in filter(str.strip, spec.split(";")):
        tokens = rule.split()
        daytypes = {WEEKDAY, SATURDAY, SUNDAY}
        if tokens and not _TIME_RANGE.match(tokens[0].split(",")[0]):
            daytypes = _daytypes(tokens.pop(0))
        hours = _hours(tokens[0]) if tokens else set(range(HOURS))
        if len(tokens) > 1:
            raise UnsupportedCondition(rule)
        buckets |= {d * HOURS + h for d in daytypes for h in hours}
    return buckets


def _daytypes(token: str) -> set[int]:
    days: set[int] = set()
    for part in token.split(","):
        m = _DAY_TOKEN.match(part)
        if not m:
            raise UnsupportedCondition(token)
        start = _DAYS[m.group(1)]
        end = _DAYS[m.group(2)] if m.group(2) else start
        days |= {d % 7 for d in range(start, end + (7 if end < start else 0) + 1)}
    # Weekdays share one bucket profile, so any weekday restriction covers all weekdays (conservative).
    return ({WEEKDAY} if days & {0, 1, 2, 3, 4} else set()) | ({SATURDAY} if 5 in days else set()) \
        | ({SUNDAY} if 6 in days else set())


def _hours(token: str) -> set[int]:
    hours: set[int] = set()
    for rng in token.split(","):
        m = _TIME_RANGE.match(rng)
        if not m:
            raise UnsupportedCondition(token)
        start = int(m.group(1)) * 60 + int(m.group(2))
        end = int(m.group(3)) * 60 + int(m.group(4))
        if end <= start:
            end += 24 * 60
        hours |= {(minute // 60) % HOURS for minute in range(start, end)}
    return hours


# --------------------------------------------------------------------------- #
# Zones
# --------------------------------------------------------------------------- #

def zone_kind(tags: dict[str, str]) -> ZoneKind | None:
    if tags.get("landuse") == "military" or "military" in tags:
        return ZoneKind.NO_ENTRY
    return None


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #

@dataclass
class OsmExtract:
    edges: dict[str, EdgeMeta]
    zones: list[RestrictedZone]
    stats: Counter


def build_edges(way_id: int, tags: dict[str, str], nodes: list[tuple[int, float, float]],
                legal: LegalSpeedDefaults, uniform_kmh: float, stats: Counter) -> list[EdgeMeta]:
    highway = tags.get("highway", "")
    road_class = HIGHWAY_CLASS.get(highway)
    if road_class is None or tags.get("area") == "yes" or len(nodes) < 2:
        return []
    access, toll = parse_access(tags), parse_toll(tags)
    no_access, parsed = parse_conditional(tags)
    divided = is_divided(tags)
    oneway = parse_oneway(tags, highway)
    stats["ways"] += 1
    stats[f"access.{access.value}"] += 1
    stats[f"toll.{toll.value}"] += 1
    if not parsed:
        stats["conditional.unparsed"] += 1
    elif no_access:
        stats["conditional.parsed"] += 1

    directions = [("forward", nodes)] if oneway >= 0 else []
    if oneway <= 0:
        directions.append(("backward", nodes[::-1]))
    edges = []
    for direction, seq in directions:
        max_speed, source = maxspeed_for(tags, direction, road_class, divided, legal)
        stats[f"maxspeed.{source.value}"] += 1
        for (a, alat, alon), (b, blat, blon) in zip(seq, seq[1:]):
            edges.append(EdgeMeta(
                segment_id=f"{way_id}:{a}:{b}", from_node=str(a), to_node=str(b), road_class=road_class,
                distance_m=haversine_m((alat, alon), (blat, blon)),
                speed_kmh=expected_speed_kmh(max_speed, uniform_kmh), osm_way_id=way_id,
                geometry=((alat, alon), (blat, blon)), max_speed_kmh=max_speed, max_speed_source=source,
                road_access=access, toll=toll, no_access_buckets=no_access))
    stats["segments"] += len(edges)
    return edges


def extract(path: str, legal: LegalSpeedDefaults = INDIA_M1,
            uniform_kmh: float = UNIFORM_SPEED_KMH) -> OsmExtract:
    import osmium  # optional dependency: only needed to read files

    edges: dict[str, EdgeMeta] = {}
    zones: list[RestrictedZone] = []
    stats: Counter = Counter()

    class Handler(osmium.SimpleHandler):
        def way(self, w):
            tags = {t.k: t.v for t in w.tags}
            if "highway" not in tags:
                return
            nodes = [(n.ref, n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()]
            for e in build_edges(w.id, tags, nodes, legal, uniform_kmh, stats):
                edges[e.segment_id] = e

        def area(self, a):
            tags = {t.k: t.v for t in a.tags}
            kind = zone_kind(tags)
            if kind is None:
                return
            for ring in a.outer_rings():
                zones.append(RestrictedZone(
                    zone_id=f"osm_{'w' if a.from_way() else 'r'}{a.orig_id()}_{len(zones)}", kind=kind,
                    polygon=tuple((n.lat, n.lon) for n in ring), name=tags.get("name", ""), source="osm"))
                stats[f"zones.{kind.value}"] += 1

    Handler().apply_file(path, locations=True)
    return OsmExtract(edges, zones, stats)


# --------------------------------------------------------------------------- #
# JSON I/O
# --------------------------------------------------------------------------- #

def _edge_json(e: EdgeMeta) -> dict:
    d = asdict(e)
    d["no_access_buckets"] = sorted(e.no_access_buckets) if e.no_access_buckets else None
    return d


def save(ex: OsmExtract, path: str) -> None:
    payload = {
        "edges": [_edge_json(e) for e in ex.edges.values()],
        "zones": [{**asdict(z), "active_buckets": sorted(z.active_buckets) if z.active_buckets else None}
                  for z in ex.zones],
        "stats": dict(ex.stats),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def load(path: str) -> tuple[dict[str, EdgeMeta], list[RestrictedZone]]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    edges = {}
    for d in payload["edges"]:
        e = EdgeMeta(**{**d, "geometry": tuple(map(tuple, d["geometry"]))})
        e = replace(e, road_class=RoadClass(e.road_class), road_access=RoadAccess(e.road_access),
                    toll=Toll(e.toll),
                    max_speed_source=SpeedLimitSource(e.max_speed_source) if e.max_speed_source else None,
                    no_access_buckets=frozenset(e.no_access_buckets) if e.no_access_buckets else None)
        edges[e.segment_id] = e
    zones = [RestrictedZone(**{**z, "kind": ZoneKind(z["kind"]), "polygon": tuple(map(tuple, z["polygon"])),
                               "active_buckets": frozenset(z["active_buckets"]) if z["active_buckets"] else None})
             for z in payload["zones"]]
    return edges, zones


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("osm_file")
    parser.add_argument("--out", required=True)
    parser.add_argument("--city-cap", type=float, default=None,
                        help="city speed limit (km/h) applied to non-expressway legal defaults")
    args = parser.parse_args(argv)
    ex = extract(args.osm_file, replace(INDIA_M1, city_cap_kmh=args.city_cap))
    save(ex, args.out)
    for key, count in sorted(ex.stats.items()):
        print(f"{key:32s} {count}")


if __name__ == "__main__":
    main()
