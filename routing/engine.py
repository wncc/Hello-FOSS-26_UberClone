"""Routing engine: local A* backend and the service facade the rest of the app calls."""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol

from .cost import edge_cost, edge_time_s, route_eta_s
from .graph import RoadGraph, haversine_m
from .models import (
    MAX_SPEED, CustomModel, EdgeEvaluation, EdgeMeta, RestrictedZone, RoadHealth, RouteResult,
    SegmentExposure, SpeedSample, Statement, Target,
)
from .restrictions import (
    RouteOptions, conditional_statements, has_car_toll, request_statements, zone_statements,
)
from .rule_engine import CompiledModel, baseline_model, merge_models
from .speed_model import DEFAULT_SPEED_POLICY, FittedSpeedModel, SpeedModelPolicy, fit_speed_model
from .telemetry import DEFAULT_POLICY, TelemetryPolicy, aggregate, derive_rules
from .time_buckets import TimeBuckets

LatLon = tuple[float, float]


class RouterBackend(Protocol):
    def route(self, start: LatLon, end: LatLon, model: CustomModel) -> RouteResult | None: ...


class LocalAStarRouter:
    """Reference implementation of the cost formula; GraphHopper does the same at scale."""

    def __init__(self, graph: RoadGraph):
        self.graph = graph

    def route(self, start: LatLon, end: LatLon, model: CustomModel) -> RouteResult | None:
        g = self.graph
        compiled = CompiledModel(model)
        src, dst = g.nearest_node(start), g.nearest_node(end)
        goal = g.nodes[dst]
        # Admissible: overlays never raise speed above map speed nor priority above 1.
        vmax_mps = g.max_speed_kmh / 3.6
        di = model.distance_influence

        def heuristic(node: str) -> float:
            d = haversine_m(g.nodes[node], goal)
            return d / vmax_mps + di * d / 1000.0

        evals: dict[str, EdgeEvaluation] = {}
        best: dict[str, float] = {src: 0.0}
        parent: dict[str, EdgeMeta] = {}
        tie = itertools.count()
        heap = [(heuristic(src), next(tie), src)]
        closed: set[str] = set()

        while heap:
            _, _, node = heapq.heappop(heap)
            if node == dst:
                return self._build(src, dst, parent, evals, best[dst])
            if node in closed:
                continue
            closed.add(node)
            for edge in g.out.get(node, ()):
                ev = evals.get(edge.segment_id)
                if ev is None:
                    ev = evals[edge.segment_id] = compiled.evaluate(edge)
                c = edge_cost(edge.distance_m, ev.speed_kmh, ev.priority, di)
                if math.isinf(c):
                    continue
                cand = best[node] + c
                if cand < best.get(edge.to_node, math.inf):
                    best[edge.to_node] = cand
                    parent[edge.to_node] = edge
                    heapq.heappush(heap, (cand + heuristic(edge.to_node), next(tie), edge.to_node))
        return None

    @staticmethod
    def _build(src: str, dst: str, parent: dict[str, EdgeMeta],
               evals: dict[str, EdgeEvaluation], cost: float) -> RouteResult:
        path: list[EdgeMeta] = []
        node = dst
        while node != src:
            edge = parent[node]
            path.append(edge)
            node = edge.from_node
        path.reverse()
        explanation = [evals[e.segment_id] for e in path]
        return RouteResult(
            segments=[e.segment_id for e in path],
            nodes=[src, *(e.to_node for e in path)],
            cost=cost,
            distance_m=sum(e.distance_m for e in path),
            eta_s=sum(edge_time_s(e.distance_m, ev.speed_kmh) for e, ev in zip(path, explanation)),
            explanation=explanation,
        )


class RoutingService:
    """Entry point for the rest of the platform.

    Holds the baseline model, the current telemetry rules and ops rules, and
    delegates path finding to a backend (local A* or GraphHopper).

    With `buckets` set, it also learns time-of-week traffic: the fitted speed
    model supplies per-departure traffic rules and a time-aware ETA.

    Map restrictions (access, speed limits, time-based closures, restricted
    zones) come from the edges and `zones`, e.g. as produced by osm_import.
    """

    def __init__(self, backend: RouterBackend, edges: dict[str, EdgeMeta],
                 base: CustomModel | None = None, policy: TelemetryPolicy = DEFAULT_POLICY,
                 buckets: TimeBuckets | None = None,
                 speed_policy: SpeedModelPolicy = DEFAULT_SPEED_POLICY,
                 zones: list[RestrictedZone] = ()):
        self.backend = backend
        self.edges = edges
        self.base = base or baseline_model()
        _check_expected_speeds(self.base, edges)
        self.zones = {z.zone_id: z for z in zones}
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
        """Refit the speed model and recompute telemetry rules (run on a schedule, e.g. every 15 min)."""
        now = now or datetime.now(timezone.utc)
        if self.buckets:
            self.speed_model = fit_speed_model(self.edges, speed_samples, now, self.buckets,
                                               policy=self.speed_policy)
        previously_active = {r.rule_id for r in self.telemetry_rules
                             if r.expires_at is None or now < r.expires_at}
        stats = aggregate(speed_samples, exposures, now, self.policy, self.speed_model)
        rules, health = derive_rules(self.edges, stats, now, previously_active, self.policy, self.speed_model)
        self.telemetry_rules = rules
        self.health = {h.segment_id: h for h in health}
        return rules

    def set_ops_rules(self, rules: list[Statement]) -> None:
        self.ops_rules = list(rules)

    def model_for_request(self, now: datetime | None = None, depart_at: datetime | None = None,
                          options: RouteOptions | None = None) -> CustomModel:
        now = now or datetime.now(timezone.utc)
        bucket = self.buckets.of(depart_at or now) if self.buckets else None
        traffic = self.speed_model.traffic_statements(bucket) if self.speed_model and bucket is not None else []
        layers = [self.map_rules, self.telemetry_rules, self.ops_rules, traffic, request_statements(options)]
        return merge_models(self.base, layers, now, bucket, self.zones)

    def eta_s(self, path: list[EdgeMeta], depart_at: datetime, fallback_s: float) -> float:
        return route_eta_s(path, depart_at, self.speed_model.speed_kmh) if self.speed_model and path else fallback_s

    def route(self, start: LatLon, end: LatLon, now: datetime | None = None,
              depart_at: datetime | None = None, options: RouteOptions | None = None) -> RouteResult | None:
        now = now or datetime.now(timezone.utc)
        depart_at = depart_at or now
        result = self.backend.route(start, end, self.model_for_request(now, depart_at, options))
        if result is None:
            return None
        path = [self.edges[s] for s in result.segments if s in self.edges]
        return replace(result, eta_s=self.eta_s(path, depart_at, result.eta_s),
                       toll_segments=[e.segment_id for e in path if has_car_toll(e)])


def _check_expected_speeds(base: CustomModel, edges: dict[str, EdgeMeta]) -> None:
    """Telemetry measures slowness against edge.speed_kmh; it must match what the baseline routes with."""
    limits = [s.value for s in base.speed if s.target is Target.SPEED and isinstance(s.value, (int, float))]
    if not limits:
        return
    uniform = min(limits)
    uses_limit = any(s.value == MAX_SPEED for s in base.speed)

    def expected(e: EdgeMeta) -> float:
        return min(uniform, e.max_speed_kmh) if uses_limit and e.max_speed_kmh is not None else uniform

    mismatched = [e.segment_id for e in edges.values() if e.speed_kmh != expected(e)]
    if mismatched:
        raise ValueError(f"baseline expects min({uniform} km/h, legal limit) on every road, but "
                         f"{len(mismatched)} edges differ (e.g. {mismatched[0]}); "
                         f"set speed_kmh with models.expected_speed_kmh()")
