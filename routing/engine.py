"""Routing engine: local edge-based A* backend and the service facade the rest of the app calls."""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol

from .cost import edge_cost, moving_speed_kmh, route_time_breakdown
from .graph import RoadGraph, graph_from_edges, haversine_m
from .models import (
    CustomModel, EdgeEvaluation, EdgeMeta, RestrictedZone, RoadHealth, RouteResult, SegmentExposure,
    SpeedSample, Statement,
)
from .restrictions import RouteOptions, conditional_statements, has_toll, request_statements, zone_statements
from .rule_engine import CompiledModel, baseline_model, merge_models, zone_members
from .speed_model import DEFAULT_SPEED_POLICY, FittedSpeedModel, SpeedModelPolicy, fit_speed_model
from .telemetry import DEFAULT_POLICY, TelemetryPolicy, aggregate, derive_rules
from .time_buckets import TimeBuckets
from .turns import NO_RESTRICTIONS, TurnModel, TurnRestrictions
from .vehicles import CAR, PROFILES, VehicleProfile, VehicleType

LatLon = tuple[float, float]


class RouterBackend(Protocol):
    def route(self, start: LatLon, end: LatLon, model: CustomModel,
              turns: TurnModel | None = None) -> RouteResult | None: ...


class LocalAStarRouter:
    """Reference implementation; GraphHopper does the same at scale.

    Edge-based search (the state is the segment you arrived on), so turn costs and
    banned turns can depend on where you came from. Per segment:
        cost = distance / (speed x priority)  +  wait at its end node  (+ turn cost into it)
    Waits and turns are plain seconds: they are never scaled by the road's priority.
    """

    def __init__(self, graph: RoadGraph):
        self.graph = graph

    def route(self, start: LatLon, end: LatLon, model: CustomModel,
              turns: TurnModel | None = None) -> RouteResult | None:
        g = self.graph
        compiled = CompiledModel(model)
        src, dst = g.nearest_node(start, "start"), g.nearest_node(end, "end")
        if src is None or dst is None:
            return None              # outside the mapped area
        if src == dst:
            return RouteResult([], [src], 0.0, 0.0, 0.0, [])
        goal = g.nodes[dst]
        # Admissible: overlays never raise speed above expected speed nor priority above 1,
        # and waits / turn costs are >= 0.
        vmax_mps = g.max_speed_kmh / 3.6
        di = model.distance_influence

        def heuristic(node: str) -> float:
            d = haversine_m(g.nodes[node], goal)
            return d / vmax_mps + di * d / 1000.0

        evals: dict[str, EdgeEvaluation] = {}

        def segment_cost(edge: EdgeMeta) -> float:
            ev = evals.get(edge.segment_id)
            if ev is None:
                ev = evals[edge.segment_id] = compiled.evaluate(edge)
            c = edge_cost(edge.distance_m, ev.speed_kmh, ev.priority, di)
            # The trip ends at dst without crossing it, so its signal / toll wait does not apply.
            return c if edge.to_node == dst else c + edge.end_delay_s

        best: dict[str, float] = {}
        parent: dict[str, str | None] = {}
        tie = itertools.count()
        heap: list[tuple[float, int, str]] = []
        for edge in g.out.get(src, ()):
            c = segment_cost(edge)
            if not math.isinf(c) and c < best.get(edge.segment_id, math.inf):
                best[edge.segment_id], parent[edge.segment_id] = c, None
                heapq.heappush(heap, (c + heuristic(edge.to_node), next(tie), edge.segment_id))

        closed: set[str] = set()
        while heap:
            _, _, seg = heapq.heappop(heap)
            if seg in closed:
                continue
            closed.add(seg)
            edge = g.edges[seg]
            if edge.to_node == dst:
                return self._build(seg, parent, evals, best[seg], turns)
            for nxt in g.out.get(edge.to_node, ()):
                t = turns.cost_s(edge, nxt) if turns else 0.0
                c = segment_cost(nxt)
                if math.isinf(t) or math.isinf(c):
                    continue
                cand = best[seg] + t + c
                if cand < best.get(nxt.segment_id, math.inf):
                    best[nxt.segment_id], parent[nxt.segment_id] = cand, seg
                    heapq.heappush(heap, (cand + heuristic(nxt.to_node), next(tie), nxt.segment_id))
        return None

    def _build(self, last: str, parent: dict[str, str | None], evals: dict[str, EdgeEvaluation],
               cost: float, turns: TurnModel | None) -> RouteResult:
        segs: list[str] = []
        seg: str | None = last
        while seg is not None:
            segs.append(seg)
            seg = parent[seg]
        segs.reverse()
        path = [self.graph.edges[s] for s in segs]
        explanation = [evals[s] for s in segs]
        by_seg = {ev.segment_id: ev.speed_kmh for ev in explanation}
        driving, delays, turning = route_time_breakdown(
            path, datetime.now(timezone.utc), lambda e, _: by_seg[e.segment_id], turns)
        return RouteResult(
            segments=segs,
            nodes=[path[0].from_node, *(e.to_node for e in path)],
            cost=cost,
            distance_m=sum(e.distance_m for e in path),
            eta_s=driving + delays + turning,
            explanation=explanation,
            point_delay_s=delays,
            turn_s=turning,
        )


class RoutingService:
    """Entry point for the rest of the platform, for one vehicle type.

    Holds the baseline model, the current telemetry rules and ops rules, and
    delegates path finding to a backend (local A* or GraphHopper).

    With `buckets` set, it also learns time-of-week traffic: the fitted speed
    model supplies per-departure traffic rules and a time-aware ETA.

    Map restrictions (access, speed limits, time-based closures, restricted
    zones, point delays, turn restrictions) come from the edges, `zones` and
    `turn_restrictions`, e.g. as produced by osm_import for this vehicle.
    """

    def __init__(self, backend: RouterBackend, edges: dict[str, EdgeMeta],
                 base: CustomModel | None = None, policy: TelemetryPolicy = DEFAULT_POLICY,
                 buckets: TimeBuckets | None = None,
                 speed_policy: SpeedModelPolicy = DEFAULT_SPEED_POLICY,
                 zones: list[RestrictedZone] = (),
                 profile: VehicleProfile = CAR,
                 turn_restrictions: TurnRestrictions = NO_RESTRICTIONS,
                 area_members: dict[str, frozenset[str]] | None = None):
        self.backend = backend
        self.edges = edges
        self.profile = profile
        self.base = base or baseline_model(profile)
        _check_expected_speeds(self.base, edges)
        self.turns = TurnModel(profile.turns, turn_restrictions)
        self.zones = {z.zone_id: z for z in zones}
        self.area_members = area_members if area_members is not None else zone_members(zones, edges.values())
        self.map_rules = conditional_statements(edges.values()) + zone_statements(zones)
        if buckets is None and any(r.active_buckets for r in self.map_rules):
            raise ValueError("time-based closures or zones need `buckets` (the city's local time)")
        self.policy = policy
        self.buckets = buckets
        self.speed_policy = speed_policy
        self.telemetry_rules: list[Statement] = []
        self.ops_rules: list[Statement] = []
        self.health: dict[str, RoadHealth] = {}
        self.speed_model: FittedSpeedModel | None = None

    def refresh_telemetry(self, speed_samples: list[SpeedSample], exposures: list[SegmentExposure],
                          now: datetime | None = None) -> list[Statement]:
        """Refit the speed model and recompute telemetry rules (run on a schedule, e.g. every 15 min).

        Only this vehicle's events are used, and the expected wait at each segment's end
        node (signal, toll booth) is removed first, so point delays never read as slow roads.
        """
        now = now or datetime.now(timezone.utc)
        speed_samples = [self._without_point_delay(s) for s in speed_samples if s.vehicle is self.profile.vehicle]
        exposures = [e for e in exposures if e.vehicle is self.profile.vehicle]
        if self.buckets:
            self.speed_model = fit_speed_model(self.edges, speed_samples, now, self.buckets,
                                               policy=self.speed_policy)
        previously_active = {r.rule_id for r in self.telemetry_rules
                             if r.expires_at is None or now < r.expires_at}
        stats = aggregate(speed_samples, exposures, now, self.policy, self.speed_model)
        rules, health = derive_rules(self.edges, stats, now, previously_active, self.policy, self.speed_model,
                                     priorities=self.profile.priority)
        self.telemetry_rules = rules
        self.health = {h.segment_id: h for h in health}
        return rules

    def _without_point_delay(self, sample: SpeedSample) -> SpeedSample:
        edge = self.edges.get(sample.segment_id)
        return replace(sample, speed_kmh=moving_speed_kmh(sample.speed_kmh, edge)) if edge else sample

    def set_ops_rules(self, rules: list[Statement]) -> None:
        self.ops_rules = list(rules)

    def model_for_request(self, now: datetime | None = None, depart_at: datetime | None = None,
                          options: RouteOptions | None = None) -> CustomModel:
        now = now or datetime.now(timezone.utc)
        bucket = self.buckets.of(depart_at or now) if self.buckets else None
        traffic = self.speed_model.traffic_statements(bucket) if self.speed_model and bucket is not None else []
        layers = [self.map_rules, self.telemetry_rules, self.ops_rules, traffic, request_statements(options)]
        model = merge_models(self.base, layers, now, bucket, self.zones)
        model.area_members = self.area_members
        return model

    def route(self, start: LatLon, end: LatLon, now: datetime | None = None,
              depart_at: datetime | None = None, options: RouteOptions | None = None) -> RouteResult | None:
        now = now or datetime.now(timezone.utc)
        depart_at = depart_at or now
        result = self.backend.route(start, end, self.model_for_request(now, depart_at, options), self.turns)
        if result is None:
            return None
        path = [self.edges[s] for s in result.segments if s in self.edges]
        tolls = [e.segment_id for e in path if has_toll(e)]
        if not self.speed_model or not path:
            return replace(result, toll_segments=tolls)
        driving, delays, turning = route_time_breakdown(path, depart_at, self.speed_model.speed_kmh, self.turns)
        return replace(result, eta_s=driving + delays + turning, point_delay_s=delays, turn_s=turning,
                       toll_segments=tolls)


class MultiVehicleRouter:
    """One RoutingService per vehicle type; telemetry is split by the event's vehicle."""

    def __init__(self, services: dict[VehicleType, RoutingService]):
        self.services = services

    @classmethod
    def local(cls, extract, buckets: TimeBuckets | None = None, **kw) -> "MultiVehicleRouter":
        """Local A* services for every vehicle in an osm_import.OsmExtract."""
        # Every vehicle has the same road geometry, so zone membership is computed once.
        any_edges = next(iter(extract.edges.values()), {})
        members = zone_members(extract.zones, any_edges.values())
        return cls({
            v: RoutingService(LocalAStarRouter(graph_from_edges(edges.values())), edges, buckets=buckets,
                              zones=extract.zones, profile=PROFILES[v],
                              turn_restrictions=extract.turn_restrictions[v], area_members=members, **kw)
            for v, edges in extract.edges.items()
        })

    def route(self, vehicle: VehicleType, start: LatLon, end: LatLon, **kw) -> RouteResult | None:
        return self.services[vehicle].route(start, end, **kw)

    def refresh_telemetry(self, speed_samples: list[SpeedSample], exposures: list[SegmentExposure],
                          now: datetime | None = None) -> dict[VehicleType, list[Statement]]:
        return {v: svc.refresh_telemetry(speed_samples, exposures, now) for v, svc in self.services.items()}


def _check_expected_speeds(base: CustomModel, edges: dict[str, EdgeMeta]) -> None:
    """Telemetry measures slowness against edge.speed_kmh; it must equal what the baseline drives at."""
    compiled = CompiledModel(base)
    mismatched = [e.segment_id for e in edges.values()
                  if not math.isclose(compiled.evaluate(e).speed_kmh, e.speed_kmh, rel_tol=1e-9)]
    if mismatched:
        raise ValueError(f"{len(mismatched)} edges (e.g. {mismatched[0]}) have a speed_kmh that differs from "
                         f"the baseline's; build it with models.expected_speed_kmh()")

