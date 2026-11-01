"""Pickup ETA providers: how long a driver needs to reach a rider.

StraightLineEta works with no map at all; RouterEta uses the routing engine, so
rivers, one-ways, flyovers, banned turns and each vehicle's own rules count.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from routing import MultiVehicleRouter, VehicleType
from routing.cost import edge_cost, route_time_breakdown
from routing.rule_engine import CompiledModel
from routing.road_classes import UNIFORM_SPEED_KMH

from .geo import LatLng, haversine_km


class EtaProvider(Protocol):
    def pickup_eta_s(self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime) -> float | None:
        """Seconds, or None if the rider is unreachable for this vehicle."""

    def pickup_estimate(
        self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime
    ) -> tuple[float, float] | None:
        """(distance_m, duration_s) or None if unreachable."""


class StraightLineEta:
    """Straight-line distance x a typical city detour factor, at the uniform routing speed."""

    def __init__(self, speed_kmh: float = UNIFORM_SPEED_KMH, detour_factor: float = 1.4):
        self.speed_kmh = speed_kmh
        self.detour_factor = detour_factor

    def pickup_eta_s(self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime) -> float | None:
        return haversine_km(driver, rider) * self.detour_factor / self.speed_kmh * 3600.0

    def pickup_estimate(
        self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime
    ) -> tuple[float, float]:
        km = haversine_km(driver, rider) * self.detour_factor
        return km * 1000.0, km / self.speed_kmh * 3600.0


class RouterEta:
    def __init__(self, router: MultiVehicleRouter):
        self.router = router

    def pickup_eta_s(
        self,
        driver: LatLng,
        rider: LatLng,
        vehicle: VehicleType,
        at: datetime,
    ) -> float | None:
        if vehicle not in self.router.services:
            return None
        result = self.router.route(vehicle, driver, rider, now=at, depart_at=at)
        return None if result is None else result.eta_s

    def pickup_estimate(
        self,
        driver: LatLng,
        rider: LatLng,
        vehicle: VehicleType,
        at: datetime,
    ) -> tuple[float, float] | None:
        """(distance_m, duration_s) or None if unreachable."""
        if vehicle not in self.router.services:
            return None
        result = self.router.route(vehicle, driver, rider, now=at, depart_at=at)
        return None if result is None else (result.distance_m, result.eta_s)

    def pickup_etas_s(
        self,
        drivers: dict[str, LatLng],
        rider: LatLng,
        vehicle: VehicleType,
        at: datetime,
    ) -> dict[str, float | None]:
        """Calculate pickup ETAs for multiple drivers with one reverse search."""
        service = self.router.services.get(vehicle)
        if service is None:
            return {driver_id: None for driver_id in drivers}

        backend = service.backend
        reverse_search = getattr(backend, "reverse_costs", None)

        # Backends without reverse search retain the existing behavior.
        if reverse_search is None:
            return {
                driver_id: self.pickup_eta_s(position, rider, vehicle, at)
                for driver_id, position in drivers.items()
            }

        model = service.model_for_request(at, at)
        graph = backend.graph

        # Find each driver's start node first, so the search can stop early.
        sources = {
            driver_id: graph.nearest_node(position, "start")
            for driver_id, position in drivers.items()
        }
        groups = [
            [edge.segment_id for edge in graph.out.get(node, ())]
            for node in sources.values() if node is not None
        ]
        groups = [segs for segs in groups if segs]

        compiled = CompiledModel(model)

        destination, remaining, next_segment = reverse_search(
            rider, model, service.turns, groups=groups, compiled=compiled
        )

        if destination is None:
            return {driver_id: None for driver_id in drivers}

        evaluations = {}
        results = {}

        def weighted_edge_cost(edge):
            evaluation = evaluations.get(edge.segment_id)
            if evaluation is None:
                evaluation = evaluations[edge.segment_id] = compiled.evaluate(edge)

            cost = edge_cost(
                edge.distance_m,
                evaluation.speed_kmh,
                evaluation.priority,
                model.distance_influence,
            )
            if edge.to_node != destination:
                cost += edge.end_delay_s
            return cost

        if service.speed_model:
            speed_fn = service.speed_model.speed_kmh
        else:
            speed_fn = lambda edge, _when: compiled.evaluate(edge).speed_kmh

        for driver_id in drivers:
            source = sources[driver_id]

            if source is None:
                results[driver_id] = None
                continue

            if source == destination:
                results[driver_id] = 0.0
                continue

            # Pick the best first segment using the reverse-search results.
            candidates = []
            for edge in graph.out.get(source, ()):
                if edge.segment_id not in remaining:
                    continue
                cost = weighted_edge_cost(edge) + remaining[edge.segment_id]
                candidates.append((cost, edge.segment_id))

            if not candidates:
                results[driver_id] = None
                continue

            _, first_segment = min(candidates)
            path = []
            segment_id = first_segment
            visited = set()

            while segment_id is not None:
                if segment_id in visited:
                    break
                visited.add(segment_id)
                path.append(graph.edges[segment_id])
                segment_id = next_segment.get(segment_id)

            if not path or segment_id is not None:
                results[driver_id] = None
                continue

            driving, delays, turning = route_time_breakdown(
                path, at, speed_fn, service.turns
            )
            eta = driving + delays + turning
            results[driver_id] = None if math.isinf(eta) else eta

        return results