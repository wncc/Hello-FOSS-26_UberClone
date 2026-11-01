"""Driver GPS updates: keep the latest position for matching, store breadcrumbs for routing
telemetry, and forward the position to the rider during an active trip."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from routing import VehicleType

from ..context import AppContext
from ..models import DriverProfile, LocationPing, RideStatus, User
from ..schemas import LocationIn
from .rides import active_ride_of

ETA_INTERVAL_S = 15.0
_last_eta_at: dict[str, datetime] = {}


async def update_location(session: AsyncSession, ctx: AppContext, driver: User, profile: DriverProfile,
                          loc: LocationIn) -> None:
    now = datetime.now(timezone.utc)
    profile.lat, profile.lng, profile.heading, profile.location_at = loc.lat, loc.lng, loc.heading, now
    ride = await active_ride_of(session, driver)
    session.add(LocationPing(driver_id=driver.id, ride_id=ride.id if ride else None, lat=loc.lat, lng=loc.lng,
                             speed_kmh=loc.speed_kmh, heading=loc.heading, recorded_at=now))
    await session.commit()
    if ride:
        payload: dict[str, object] = {
            "ride_id": ride.id, "lat": loc.lat, "lng": loc.lng, "heading": loc.heading,
        }
        if ride.status is RideStatus.DRIVER_ASSIGNED:
            last = _last_eta_at.get(ride.id)
            if last is None or (now - last).total_seconds() >= ETA_INTERVAL_S:
                way = ctx.routes.estimate(
                    (loc.lat, loc.lng), (ride.pickup_lat, ride.pickup_lng), VehicleType(ride.vehicle_type),
                )
                if way is not None:
                    payload["approach_duration_s"] = way.duration_s
                    _last_eta_at[ride.id] = now
        else:
            _last_eta_at.pop(ride.id, None)
        await ctx.hub.send(ride.rider_id, "driver:location", payload)