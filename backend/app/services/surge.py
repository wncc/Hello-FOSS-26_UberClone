"""Zone-based surge pricing with capped exponential smoothing."""
from __future__ import annotations

import math
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..models import (
    DRIVER_BUSY_STATUSES,
    DriverProfile,
    DriverStatus,
    Ride,
    RideStatus,
)


class SurgePricing:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._multipliers: dict[tuple[int, int, str], float] = {}
        self._last_refresh: dict[tuple[int, int, str], float] = {}

    def zone(self, lat: float, lng: float) -> tuple[int, int]:
        size = self.settings.surge_zone_degrees
        return math.floor(lat / size), math.floor(lng / size)

    async def multiplier(
        self,
        session: AsyncSession,
        lat: float,
        lng: float,
        vehicle_type: str,
    ) -> float:
        if not self.settings.surge_enabled:
            return 1.0

        zone = self.zone(lat, lng)
        key = (*zone, vehicle_type)
        now = time.monotonic()

        if (
            key in self._multipliers
            and now - self._last_refresh[key] < self.settings.surge_refresh_seconds
        ):
            return self._multipliers[key]

        waiting = await session.scalars(
            select(Ride).where(
                Ride.status == RideStatus.SEARCHING,
                Ride.vehicle_type == vehicle_type,
            )
        )
        demand = sum(
            1 for ride in waiting
            if self.zone(ride.pickup_lat, ride.pickup_lng) == zone
        )

        freshness_cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.location_stale_seconds
        )

        profiles = await session.scalars(
            select(DriverProfile).where(
                DriverProfile.is_online.is_(True),
                DriverProfile.status == DriverStatus.APPROVED,
                DriverProfile.vehicle_type == vehicle_type,
                DriverProfile.lat.is_not(None),
                DriverProfile.lng.is_not(None),
                DriverProfile.location_at >= freshness_cutoff,
            )
        )
        
        busy_ids = set(
            await session.scalars(
                select(Ride.driver_id).where(
                    Ride.status.in_(DRIVER_BUSY_STATUSES),
                    Ride.driver_id.is_not(None),
                )
            )
        )
        supply = sum(
            1 for profile in profiles
            if profile.user_id not in busy_ids
            and profile.location_at is not None
            and (profile.lat, profile.lng) is not None
            and self.zone(profile.lat, profile.lng) == zone
        )

        if demand == 0:
            target = 1.0
        elif supply == 0:
            target = self.settings.surge_max_multiplier
        else:
            ratio = demand / supply
            target = min(
                self.settings.surge_max_multiplier,
                max(1.0, 1.0 + self.settings.surge_sensitivity * (ratio - 1.0)),
            )

        previous = self._multipliers.get(key, 1.0)
        alpha = self.settings.surge_smoothing_alpha
        smoothed = previous + alpha * (target - previous)
        smoothed = min(self.settings.surge_max_multiplier, max(1.0, smoothed))

        self._multipliers[key] = round(smoothed, 2)
        self._last_refresh[key] = now
        return self._multipliers[key]
