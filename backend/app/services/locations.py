"""Driver GPS updates: keep the latest position for matching, store breadcrumbs for routing
telemetry, and forward the position to the rider during an active trip."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..context import AppContext
from ..models import DriverProfile, LocationPing, User
from ..schemas import LocationIn
from .rides import active_ride_of


async def update_location(session: AsyncSession, ctx: AppContext, driver: User, profile: DriverProfile,
                          loc: LocationIn) -> None:
    now = datetime.now(timezone.utc)
    profile.lat, profile.lng, profile.heading, profile.location_at = loc.lat, loc.lng, loc.heading, now
    ride = await active_ride_of(session, driver)
    session.add(LocationPing(driver_id=driver.id, ride_id=ride.id if ride else None, lat=loc.lat, lng=loc.lng,
                             speed_kmh=loc.speed_kmh, heading=loc.heading, recorded_at=now))
    await session.commit()
    if ride:
        await ctx.hub.send(ride.rider_id, "driver:location", {
            "ride_id": ride.id, "lat": loc.lat, "lng": loc.lng, "heading": loc.heading})
