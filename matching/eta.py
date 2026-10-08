"""Pickup ETA providers: how long a driver needs to reach a rider.

StraightLineEta works with no map at all; RouterEta uses the routing engine, so
rivers, one-ways, flyovers, banned turns and each vehicle's own rules count.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from routing import MultiVehicleRouter, VehicleType
from routing.road_classes import UNIFORM_SPEED_KMH

from .geo import LatLng, haversine_km


class EtaProvider(Protocol):
    def pickup_eta_s(self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime) -> float | None:
        """Seconds, or None if the rider is unreachable for this vehicle."""


class StraightLineEta:
    """Straight-line distance x a typical city detour factor, at the uniform routing speed."""

    def __init__(self, speed_kmh: float = UNIFORM_SPEED_KMH, detour_factor: float = 1.4):
        self.speed_kmh = speed_kmh
        self.detour_factor = detour_factor

    def pickup_eta_s(self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime) -> float | None:
        return haversine_km(driver, rider) * self.detour_factor / self.speed_kmh * 3600.0


class RouterEta:
    def __init__(self, router: MultiVehicleRouter):
        self.router = router

    def pickup_eta_s(self, driver: LatLng, rider: LatLng, vehicle: VehicleType, at: datetime) -> float | None:
        if vehicle not in self.router.services:
            return None
        result = self.router.route(vehicle, driver, rider, now=at, depart_at=at)
        return None if result is None else result.eta_s
