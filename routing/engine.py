"""Routing engine: local A* backend and the service facade the rest of the app calls."""
from __future__ import annotations

import heapq
import itertools
import math
from datetime import datetime, timezone
from typing import Protocol

from .cost import edge_cost, edge_time_s
from .graph import RoadGraph, haversine_m
from .models import (
    CustomModel, EdgeEvaluation, EdgeMeta, RoadHealth, RouteResult, SegmentExposure,
    SpeedSample, Statement,
)
from .rule_engine import CompiledModel, baseline_model, merge_models
from .telemetry import DEFAULT_POLICY, TelemetryPolicy, aggregate, derive_rules

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
    """

    def __init__(self, backend: RouterBackend, edges: dict[str, EdgeMeta],
                 base: CustomModel | None = None, policy: TelemetryPolicy = DEFAULT_POLICY):
        self.backend = backend
        self.edges = edges
        self.base = base or baseline_model()
        self.policy = policy
        self.telemetry_rules: list[Statement] = []
        self.ops_rules: list[Statement] = []
        self.health: dict[str, RoadHealth] = {}

    def refresh_telemetry(self, speed_samples: list[SpeedSample], exposures: list[SegmentExposure],
                          now: datetime | None = None) -> list[Statement]:
        """Recompute telemetry rules (run on a schedule, e.g. every 15 min)."""
        now = now or datetime.now(timezone.utc)
        previously_active = {r.rule_id for r in self.telemetry_rules if r.is_active(now)}
        stats = aggregate(speed_samples, exposures, now, self.policy)
        rules, health = derive_rules(self.edges, stats, now, previously_active, self.policy)
        self.telemetry_rules = rules
        self.health = {h.segment_id: h for h in health}
        return rules

    def set_ops_rules(self, rules: list[Statement]) -> None:
        self.ops_rules = list(rules)

    def model_for_request(self, now: datetime | None = None) -> CustomModel:
        return merge_models(self.base, [self.telemetry_rules, self.ops_rules], now)

    def route(self, start: LatLon, end: LatLon, now: datetime | None = None) -> RouteResult | None:
        return self.backend.route(start, end, self.model_for_request(now))
