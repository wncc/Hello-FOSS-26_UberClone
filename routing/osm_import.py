"""Build per-vehicle road metadata from OpenStreetMap.

Extracts, for car / auto rickshaw / bike: speed limits, access, tolls, one-way,
time-based closures, point delays (traffic signals, toll booths, level
crossings), speed breakers, turn restrictions, and restricted zones.

Input: an .osm or .osm.pbf extract of the operating city, e.g. from
https://download.geofabrik.de/asia/india.html (clip to the city with `osmium extract`).
The segment ids ("<way>:<from node>:<to node>") match what GraphHopper imports from
the same file, so telemetry keyed on them lines up with routing.

    python -m routing.osm_import region.osm.pbf --out roads.pkl --bbox 18.89,72.77,19.30,73.05 [--city-cap 50]

Tag parsing is pure functions (tested without a file); the reader needs `pip install osmium`.
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from typing import Iterable

from .graph import haversine_m
from .models import (
    EdgeMeta, RestrictedZone, RoadAccess, SpeedLimitSource, Toll, ZoneKind, expected_speed_kmh,
)
from .road_classes import RoadClass
from .time_buckets import HOURS, SATURDAY, SUNDAY, WEEKDAY
from .turns import TurnRestrictions
from .vehicles import CAR, INDIA_M1, PROFILES, LegalSpeedDefaults, VehicleProfile, VehicleType

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
                 profile: VehicleProfile = CAR) -> tuple[float | None, SpeedLimitSource]:
    """A vehicle-specific sign wins; a general sign applies to everyone but, for vehicles
    with a lower category maximum (bikes, autos), never above that maximum."""
    legal = profile.legal
    for key in (f"maxspeed:{k}" for k in profile.osm_keys):
        kmh = parse_maxspeed(tags[key], legal) if key in tags else None
        if kmh is not None:
            return kmh, SpeedLimitSource.SIGN
    for key in (f"maxspeed:{direction}", "maxspeed"):
        if key not in tags:
            continue
        kmh = None if tags[key] == "none" else parse_maxspeed(tags[key], legal)
        if kmh is None and tags[key] != "none":
            continue
        if profile.cap_signs_at_category:
            cap = legal.legal_max(road_class, divided)
            kmh = cap if kmh is None else min(kmh, cap)
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

GENERIC_ACCESS_KEYS = ("motor_vehicle", "vehicle", "access")   # most -> least specific
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
ACCESS_STRICTNESS = {RoadAccess.YES: 0, RoadAccess.DESIGNATED: 0, RoadAccess.DISCOURAGED: 1,
                     RoadAccess.DESTINATION: 2, RoadAccess.DELIVERY: 3, RoadAccess.PRIVATE: 4, RoadAccess.NO: 5}
BLOCKING_ACCESS = {"no", "private", "delivery", "agricultural", "forestry", "military", "emergency", "restricted"}


def parse_access(tags: dict[str, str], profile: VehicleProfile = CAR) -> RoadAccess:
    """Most specific key wins. Profiles with several keys (auto: motorcar + motorcycle)
    take the strictest result."""
    results = []
    for specific in profile.osm_keys:
        for key in (specific, *GENERIC_ACCESS_KEYS):
            access = ACCESS_VALUES.get(tags.get(key, ""))
            if access is not None:
                results.append(access)
                break
        else:
            results.append(RoadAccess.YES)
    return max(results, key=ACCESS_STRICTNESS.__getitem__)


def parse_toll(tags: dict[str, str], profile: VehicleProfile = CAR) -> Toll:
    specific = tags.get(f"toll:{profile.toll_key}") if profile.toll_key else None
    if specific in ("yes", "no"):
        return Toll.ALL if specific == "yes" else Toll.NO
    generic = tags.get("toll")
    if generic == "yes":
        return Toll.ALL if profile.pays_toll else Toll.NO
    if generic == "no":
        return Toll.NO
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

_DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_DAY_TOKEN = re.compile(r"^(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$")


class UnsupportedCondition(ValueError):
    pass


def conditional_keys(profile: VehicleProfile = CAR) -> tuple[str, ...]:
    return tuple(f"{k}:conditional" for k in (*profile.osm_keys, *GENERIC_ACCESS_KEYS))


def parse_conditional(tags: dict[str, str], profile: VehicleProfile = CAR) -> tuple[frozenset[int] | None, bool]:
    """(buckets in which this vehicle is blocked, parsed_ok). Most specific key wins.

    Supports "no @ (Mo-Fr 07:00-11:00,17:00-21:00; Sa 10:00-14:00)". Anything
    else (dates, holidays, weight/wet conditions) is reported as not parsed and
    ignored, rather than guessed.
    """
    key = next((k for k in conditional_keys(profile) if k in tags), None)
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
# Point features on nodes: signals, toll booths, level crossings, speed breakers
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NodeInfo:
    features: frozenset[str]          # keys of VehicleProfile.point_delay_s
    signal_direction: str | None      # "forward" / "backward" relative to the way, None = both
    traffic_calming: bool


def node_info(tags: dict[str, str]) -> NodeInfo | None:
    features = set()
    if tags.get("highway") == "traffic_signals":
        features.add("traffic_signals")
    if tags.get("barrier") == "toll_booth":
        features.add("toll_booth")
    if tags.get("railway") == "level_crossing":
        features.add("level_crossing")
    calming = tags.get("traffic_calming", "no") != "no"
    if not features and not calming:
        return None
    direction = tags.get("traffic_signals:direction") or tags.get("direction")
    return NodeInfo(frozenset(features), direction if direction in ("forward", "backward") else None, calming)


def _arrival_features(info: NodeInfo | None, direction: str) -> frozenset[str]:
    if info is None:
        return frozenset()
    if "traffic_signals" in info.features and info.signal_direction not in (None, direction):
        return info.features - {"traffic_signals"}
    return info.features


# --------------------------------------------------------------------------- #
# Zones
# --------------------------------------------------------------------------- #

def zone_kind(tags: dict[str, str]) -> ZoneKind | None:
    if tags.get("landuse") == "military" or "military" in tags:
        return ZoneKind.NO_ENTRY
    return None


# --------------------------------------------------------------------------- #
# Turn restrictions
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RawRestriction:
    from_way: int
    via_node: int
    to_way: int
    tags: dict[str, str]


def restriction_for(tags: dict[str, str], profile: VehicleProfile) -> str | None:
    """'no_right_turn', 'only_straight_on', ... for this vehicle, or None if it is exempt."""
    for k in profile.osm_keys:
        if f"restriction:{k}" in tags:
            return tags[f"restriction:{k}"]
    exempt = set(tags.get("except", "").replace(" ", "").split(";"))
    if exempt and all(k in exempt for k in profile.osm_keys):
        return None
    return tags.get("restriction")


def resolve_restrictions(raw: list[RawRestriction], edges: dict[str, EdgeMeta], profile: VehicleProfile,
                         stats: Counter) -> TurnRestrictions:
    arriving: dict[tuple[int, str], list[str]] = defaultdict(list)
    leaving: dict[tuple[int, str], list[str]] = defaultdict(list)
    for e in edges.values():
        arriving[(e.osm_way_id, e.to_node)].append(e.segment_id)
        leaving[(e.osm_way_id, e.from_node)].append(e.segment_id)

    banned: set[tuple[str, str]] = set()
    only: dict[str, frozenset[str]] = {}
    for r in raw:
        kind = restriction_for(r.tags, profile)
        if not kind or not kind.startswith(("no_", "only_")):
            continue
        via = str(r.via_node)
        ins, outs = arriving.get((r.from_way, via), []), leaving.get((r.to_way, via), [])
        if not ins or not outs:
            stats[f"{profile.vehicle.value}.turn_restriction.unresolved"] += 1
            continue
        stats[f"{profile.vehicle.value}.turn_restriction.{kind.split('_')[0]}"] += 1
        for seg in ins:
            if kind.startswith("no_"):
                banned.update((seg, out) for out in outs)
            else:
                only[seg] = frozenset(outs)
    return TurnRestrictions(frozenset(banned), only)


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #

UNROUTABLE_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}


def is_routable(tags: dict[str, str]) -> bool:
    return (tags.get("highway") in HIGHWAY_CLASS and tags.get("area") != "yes"
            and tags.get("service") not in UNROUTABLE_SERVICE)


def _pieces(seq: list[tuple[int, float, float]], split_at: set[int] | None) -> list[list[tuple[int, float, float]]]:
    """Cut a way at junctions / point features; None cuts at every node."""
    pieces, start = [], 0
    for i in range(1, len(seq)):
        if i == len(seq) - 1 or split_at is None or seq[i][0] in split_at:
            pieces.append(seq[start:i + 1])
            start = i
    return pieces


def build_edges(way_id: int, tags: dict[str, str], nodes: list[tuple[int, float, float]],
                profile: VehicleProfile, nodes_info: dict[int, NodeInfo], stats: Counter,
                split_at: set[int] | None = None) -> list[EdgeMeta]:
    """Directed segments for one way. With `split_at` (junctions + feature nodes) a segment runs
    from one such node to the next and keeps the full road shape; without it, every node pair
    becomes a segment."""
    highway = tags.get("highway", "")
    road_class = HIGHWAY_CLASS.get(highway)
    if not is_routable(tags) or len(nodes) < 2:
        return []
    v = profile.vehicle.value
    access = parse_access(tags, profile)
    if road_class is RoadClass.MOTORWAY and not profile.legal.motorway_permitted:
        access = RoadAccess.NO
    toll = parse_toll(tags, profile)
    no_access, parsed = parse_conditional(tags, profile)
    divided = is_divided(tags)
    oneway = parse_oneway(tags, highway)
    way_calming = tags.get("traffic_calming", "no") != "no"
    stats[f"{v}.access.{access.value}"] += 1
    stats[f"{v}.toll.{toll.value}"] += 1
    if not parsed:
        stats[f"{v}.conditional.unparsed"] += 1
    elif no_access:
        stats[f"{v}.conditional.parsed"] += 1

    directions = [("forward", nodes)] if oneway >= 0 else []
    if oneway <= 0:
        directions.append(("backward", nodes[::-1]))
    edges = []
    for direction, seq in directions:
        max_speed, source = maxspeed_for(tags, direction, road_class, divided, profile)
        stats[f"{v}.maxspeed.{source.value}"] += 1
        for piece in _pieces(seq, split_at):
            a, b = piece[0][0], piece[-1][0]
            points = tuple((lat, lon) for _, lat, lon in piece)
            info = nodes_info.get(b)
            features = _arrival_features(info, direction)
            calming = way_calming or bool(info and info.traffic_calming)
            edges.append(EdgeMeta(
                segment_id=f"{way_id}:{a}:{b}", from_node=str(a), to_node=str(b), road_class=road_class,
                distance_m=sum(haversine_m(p, q) for p, q in zip(points, points[1:])),
                speed_kmh=expected_speed_kmh(max_speed, profile.uniform_speed_kmh, calming), osm_way_id=way_id,
                geometry=points, max_speed_kmh=max_speed, max_speed_source=source,
                road_access=access, toll=toll, no_access_buckets=no_access,
                end_delay_s=sum(profile.point_delay_s.get(f, 0.0) for f in features),
                end_features=features, traffic_calming=calming))
    stats[f"{v}.segments"] += len(edges)
    return edges


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #

@dataclass
class OsmExtract:
    edges: dict[VehicleType, dict[str, EdgeMeta]]
    zones: list[RestrictedZone]
    turn_restrictions: dict[VehicleType, TurnRestrictions]
    stats: Counter = field(default_factory=Counter)


BBox = tuple[float, float, float, float]   # min_lat, min_lng, max_lat, max_lng
READ_KEYS = ("highway", "barrier", "railway", "traffic_calming", "type", "landuse", "military")


def extract(path: str, profiles: Iterable[VehicleProfile] = PROFILES.values(),
            city_cap_kmh: float | None = None, bbox: BBox | None = None) -> OsmExtract:
    """Read an OSM file. Untagged / irrelevant objects are dropped by osmium in C++, so only
    the few objects that matter reach Python (a 220 MB regional extract reads in about a minute).
    With `bbox`, roads touching the box are kept."""
    import osmium  # optional dependency: only needed to read files

    profiles = [replace(p, legal=replace(p.legal, city_cap_kmh=city_cap_kmh)) if city_cap_kmh else p
                for p in profiles]
    zones: list[RestrictedZone] = []
    raw_restrictions: list[RawRestriction] = []
    nodes_info: dict[int, NodeInfo] = {}
    ways: list[tuple[int, dict[str, str], list[tuple[int, float, float]]]] = []
    stats: Counter = Counter()

    def inside(lat: float, lon: float) -> bool:
        return bbox is None or (bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3])

    processor = (osmium.FileProcessor(path).with_locations().with_areas()
                 .with_filter(osmium.filter.EmptyTagFilter())
                 .with_filter(osmium.filter.KeyFilter(*READ_KEYS)))
    for obj in processor:
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_node():
            info = node_info(tags)
            if info and inside(obj.location.lat, obj.location.lon):
                nodes_info[obj.id] = info
                for f in info.features:
                    stats[f"nodes.{f}"] += 1
                stats["nodes.traffic_calming"] += info.traffic_calming
        elif obj.is_way():
            if not is_routable(tags):
                continue
            nodes = [(n.ref, n.location.lat, n.location.lon) for n in obj.nodes if n.location.valid()]
            if len(nodes) >= 2 and any(inside(lat, lon) for _, lat, lon in nodes):
                ways.append((obj.id, tags, nodes))
        elif obj.is_relation():
            if tags.get("type") != "restriction":
                continue
            roles = defaultdict(list)
            for m in obj.members:
                roles[(m.role, m.type)].append(m.ref)
            frm, via, to = roles[("from", "w")], roles[("via", "n")], roles[("to", "w")]
            if len(frm) == 1 and len(via) == 1 and len(to) == 1:
                raw_restrictions.append(RawRestriction(frm[0], via[0], to[0], tags))
            else:
                stats["turn_restriction.unsupported"] += 1  # via-way or malformed
        elif obj.is_area():
            kind = zone_kind(tags)
            if kind is None:
                continue
            for ring in obj.outer_rings():
                polygon = tuple((n.lat, n.lon) for n in ring)
                if not any(inside(lat, lon) for lat, lon in polygon):
                    continue
                zones.append(RestrictedZone(
                    zone_id=f"osm_{'w' if obj.from_way() else 'r'}{obj.orig_id()}_{len(zones)}", kind=kind,
                    polygon=polygon, name=tags.get("name", ""), source="osm"))
                stats[f"zones.{kind.value}"] += 1

    # Segments run between junctions (nodes shared by several roads) and point features.
    uses = Counter(ref for _, _, nodes in ways for ref, _, _ in nodes)
    split_at = {ref for ref, n in uses.items() if n > 1} | set(nodes_info)
    edges: dict[VehicleType, dict[str, EdgeMeta]] = {p.vehicle: {} for p in profiles}
    for way_id, tags, nodes in ways:
        stats["ways"] += 1
        for p in profiles:
            for e in build_edges(way_id, tags, nodes, p, nodes_info, stats, split_at):
                edges[p.vehicle][e.segment_id] = e
    restrictions = {p.vehicle: resolve_restrictions(raw_restrictions, edges[p.vehicle], p, stats) for p in profiles}
    return OsmExtract(edges, zones, restrictions, stats)


# --------------------------------------------------------------------------- #
# JSON I/O
# --------------------------------------------------------------------------- #

def _edge_json(e: EdgeMeta) -> dict:
    d = asdict(e)
    d["no_access_buckets"] = sorted(e.no_access_buckets) if e.no_access_buckets else None
    d["end_features"] = sorted(e.end_features)
    return d


def _edge_from_json(d: dict) -> EdgeMeta:
    return EdgeMeta(**{
        **d,
        "road_class": RoadClass(d["road_class"]),
        "geometry": tuple(map(tuple, d["geometry"])),
        "road_access": RoadAccess(d["road_access"]),
        "toll": Toll(d["toll"]),
        "max_speed_source": SpeedLimitSource(d["max_speed_source"]) if d["max_speed_source"] else None,
        "no_access_buckets": frozenset(d["no_access_buckets"]) if d["no_access_buckets"] else None,
        "end_features": frozenset(d["end_features"]),
    })


def save(ex: OsmExtract, path: str) -> None:
    """JSON (portable, readable) or, for paths ending in .pkl, a pickle that loads in seconds."""
    if path.endswith(".pkl"):
        with open(path, "wb") as f:
            pickle.dump(ex, f, protocol=pickle.HIGHEST_PROTOCOL)
        return
    payload = {
        "vehicles": {
            v.value: {
                "edges": [_edge_json(e) for e in ex.edges[v].values()],
                "turn_restrictions": {
                    "banned": sorted(map(list, ex.turn_restrictions[v].banned)),
                    "only": {k: sorted(outs) for k, outs in ex.turn_restrictions[v].only.items()},
                },
            } for v in ex.edges
        },
        "zones": [{**asdict(z), "active_buckets": sorted(z.active_buckets) if z.active_buckets else None}
                  for z in ex.zones],
        "stats": dict(ex.stats),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def load(path: str) -> OsmExtract:
    if path.endswith(".pkl"):
        with open(path, "rb") as f:
            return pickle.load(f)   # only load files you created yourself with save()
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    edges, restrictions = {}, {}
    for v, data in payload["vehicles"].items():
        vehicle = VehicleType(v)
        edges[vehicle] = {d["segment_id"]: _edge_from_json(d) for d in data["edges"]}
        tr = data["turn_restrictions"]
        restrictions[vehicle] = TurnRestrictions(frozenset(map(tuple, tr["banned"])),
                                                 {k: frozenset(outs) for k, outs in tr["only"].items()})
    zones = [RestrictedZone(**{**z, "kind": ZoneKind(z["kind"]), "polygon": tuple(map(tuple, z["polygon"])),
                               "active_buckets": frozenset(z["active_buckets"]) if z["active_buckets"] else None})
             for z in payload["zones"]]
    return OsmExtract(edges, zones, restrictions, Counter(payload.get("stats", {})))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("osm_file")
    parser.add_argument("--out", required=True)
    parser.add_argument("--city-cap", type=float, default=None,
                        help="city speed limit (km/h) applied to non-expressway legal defaults")
    parser.add_argument("--bbox", type=lambda s: tuple(float(x) for x in s.split(",")), default=None,
                        help="min_lat,min_lng,max_lat,max_lng: keep only roads touching this box")
    args = parser.parse_args(argv)
    ex = extract(args.osm_file, city_cap_kmh=args.city_cap, bbox=args.bbox)
    save(ex, args.out)
    for key, count in sorted(ex.stats.items()):
        print(f"{key:40s} {count}")


if __name__ == "__main__":
    main()
