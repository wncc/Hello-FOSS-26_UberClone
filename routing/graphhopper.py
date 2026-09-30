"""GraphHopper adapter: serialize our CustomModel and call the /route endpoint.

Recommended deployment
  * Put the baseline model in the server profile (config.yml), so the profile's
    LM preparation is built on the hierarchy.
  * Send only overlays per request (include_baseline=False). GraphHopper
    appends request statements to the profile's statements, and because our
    overlays only ever *lower* speed/priority, LM stays valid.

Segment targeting
  Stock GraphHopper has no stable per-edge id usable in expressions, so the
  default "area" mode wraps each targeted segment in a thin GeoJSON corridor
  and narrows the match with its road_class. For thousands of long-lived rules,
  bake them into a custom encoded value at import and use "expression" mode.
"""
from __future__ import annotations

import json
import logging
import math
import re
import urllib.request
from dataclasses import dataclass

from .models import (
    EDGE_AVERAGE_SPEED, Always, Condition, CustomModel, EdgeMeta, RoadClassIs,
    RouteResult, SegmentIs, Source, Statement,
)

log = logging.getLogger(__name__)
LatLon = tuple[float, float]
M_PER_DEG_LAT = 111_320.0


def area_id(segment_id: str) -> str:
    return "seg_" + re.sub(r"[^A-Za-z0-9_]", "_", segment_id)


def condition_expr(cond: Condition, segment_mode: str = "area") -> str:
    if isinstance(cond, Always):
        return "true"
    if isinstance(cond, RoadClassIs):
        return f"road_class == {cond.road_class.value}"
    if isinstance(cond, SegmentIs):
        base = (f"in_{area_id(cond.segment_id)}" if segment_mode == "area"
                else f"segment_id == {cond.segment_id}")  # requires a custom encoded value
        return f"{base} && road_class == {cond.road_class.value}" if cond.road_class else base
    raise TypeError(f"unsupported condition {cond!r}")


def statement_json(stmt: Statement, segment_mode: str = "area") -> dict:
    value = stmt.value if stmt.value == EDGE_AVERAGE_SPEED else float(stmt.value)
    return {"if": condition_expr(stmt.condition, segment_mode), stmt.op.value: value}


def corridor_polygon(geometry: tuple[LatLon, ...], half_width_m: float = 6.0,
                     trim_m: float = 4.0) -> list[list[float]] | None:
    """Thin polygon around a polyline, trimmed at both ends to avoid catching junctions."""
    if len(geometry) < 2:
        return None
    lat0 = geometry[0][0]
    kx = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    pts = [((lon - geometry[0][1]) * kx, (lat - lat0) * M_PER_DEG_LAT) for lat, lon in geometry]

    def trim(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length <= 2 * trim_m:
            return p
        return (p[0] + dx / length * trim_m, p[1] + dy / length * trim_m)

    pts[0] = trim(pts[0], pts[1])
    pts[-1] = trim(pts[-1], pts[-2])

    left, right = [], []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n * half_width_m, dx / n * half_width_m
        left.append((x + nx, y + ny))
        right.append((x - nx, y - ny))

    ring = left + right[::-1] + [left[0]]
    return [[geometry[0][1] + x / kx, lat0 + y / M_PER_DEG_LAT] for x, y in ring]


def to_graphhopper(model: CustomModel, edges: dict[str, EdgeMeta], include_baseline: bool = True,
                   segment_mode: str = "area") -> dict:
    features = {}
    out = {"speed": [], "priority": [], "distance_influence": model.distance_influence}
    if include_baseline:
        out["priority"].append({"if": "!car_access", "multiply_by": "0"})
    for stmt in model.statements():
        if stmt.source is Source.BASELINE and not include_baseline:
            continue
        if isinstance(stmt.condition, SegmentIs) and segment_mode == "area":
            seg = stmt.condition.segment_id
            edge = edges.get(seg)
            polygon = corridor_polygon(edge.geometry) if edge else None
            if polygon is None:
                log.warning("skipping %s: no geometry for segment %s", stmt.rule_id, seg)
                continue
            features[area_id(seg)] = {
                "type": "Feature", "id": area_id(seg), "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [polygon]},
            }
        out[stmt.target.value].append(statement_json(stmt, segment_mode))
    if features:
        out["areas"] = {"type": "FeatureCollection", "features": list(features.values())}
    return out


def select_overlays_near(model: CustomModel, edges: dict[str, EdgeMeta], start: LatLon, end: LatLon,
                         margin_deg: float = 0.05, max_rules: int = 200) -> CustomModel:
    """Keep only segment rules around the trip bbox, strongest first, to bound request size."""
    lat_lo, lat_hi = sorted((start[0], end[0]))
    lon_lo, lon_hi = sorted((start[1], end[1]))

    def near(stmt: Statement) -> bool:
        if not isinstance(stmt.condition, SegmentIs):
            return True
        edge = edges.get(stmt.condition.segment_id)
        return bool(edge and edge.geometry) and any(
            lat_lo - margin_deg <= lat <= lat_hi + margin_deg and lon_lo - margin_deg <= lon <= lon_hi + margin_deg
            for lat, lon in edge.geometry)

    def keep(stmts: list[Statement]) -> list[Statement]:
        fixed = [s for s in stmts if not isinstance(s.condition, SegmentIs)]
        seg = sorted((s for s in stmts if isinstance(s.condition, SegmentIs) and near(s)),
                     key=lambda s: float(s.value))
        return fixed + seg[:max_rules]

    return CustomModel(keep(model.speed), keep(model.priority), model.distance_influence)


@dataclass
class GraphHopperRouter:
    base_url: str
    edges: dict[str, EdgeMeta]
    profile: str = "car"
    include_baseline: bool = False
    segment_mode: str = "area"
    timeout_s: float = 5.0

    def request_body(self, start: LatLon, end: LatLon, model: CustomModel) -> dict:
        model = select_overlays_near(model, self.edges, start, end)
        return {
            "profile": self.profile,
            "ch.disable": True,  # per-request custom models need the flexible (LM/Dijkstra) path
            "points": [[start[1], start[0]], [end[1], end[0]]],
            "custom_model": to_graphhopper(model, self.edges, self.include_baseline, self.segment_mode),
            "points_encoded": False,
            "details": ["road_class", "average_speed"],
        }

    def route(self, start: LatLon, end: LatLon, model: CustomModel) -> RouteResult | None:
        body = json.dumps(self.request_body(start, end, model)).encode()
        req = urllib.request.Request(f"{self.base_url.rstrip('/')}/route", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.load(resp)
        paths = payload.get("paths") or []
        if not paths:
            return None
        p = paths[0]
        return RouteResult(
            segments=[], nodes=[],
            cost=float(p.get("weight", math.nan)),
            distance_m=float(p["distance"]),
            eta_s=float(p["time"]) / 1000.0,
            explanation=[],
            geometry=[(lat, lon) for lon, lat, *_ in p.get("points", {}).get("coordinates", [])],
        )
