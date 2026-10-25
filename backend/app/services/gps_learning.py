"""Persist GPS-derived junction delays and rebuild routing models."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing import VehicleType
from routing.delay_extraction import extract_delay_observations
from routing.delay_model import (
    DEFAULT_DELAY_POLICY,
    DelayKind,
    DelayObservation,
)
from routing.map_matching import GPSObservation

from ..context import AppContext
from ..models import GPSDelayObservation, LocationPing

log = logging.getLogger(__name__)


def _to_delay_observation(row: GPSDelayObservation) -> DelayObservation:
    return DelayObservation(
        kind=DelayKind(row.kind),
        junction_id=row.junction_id,
        driver_id=row.driver_id,
        observed_at=row.observed_at,
        wait_s=row.wait_s,
        inbound_segment=row.inbound_segment,
        outbound_segment=row.outbound_segment,
    )


async def _observations_for_vehicle(
    session: AsyncSession,
    vehicle: VehicleType,
    now: datetime,
) -> list[DelayObservation]:
    cutoff = now - timedelta(days=DEFAULT_DELAY_POLICY.window_days)
    rows = await session.scalars(
        select(GPSDelayObservation).where(
            GPSDelayObservation.vehicle_type == vehicle.value,
            GPSDelayObservation.observed_at >= cutoff,
            GPSDelayObservation.observed_at <= now,
        )
    )
    return [_to_delay_observation(row) for row in rows]


async def learn_from_completed_ride(
    session: AsyncSession,
    ctx: AppContext,
    ride,
) -> int:
    """Store one ride's candidate delays and refit its vehicle's model."""
    router = ctx.routes.router
    if router is None or not ride.driver_id:
        return 0

    try:
        vehicle = VehicleType(ride.vehicle_type)
    except ValueError:
        log.warning("Unknown vehicle type %r for ride %s", ride.vehicle_type, ride.id)
        return 0

    service = router.services.get(vehicle)
    if service is None or service.buckets is None:
        return 0

    now = datetime.now(timezone.utc)

    # Existing observations mean this ride has already been extracted.
    existing_id = await session.scalar(
        select(GPSDelayObservation.id)
        .where(GPSDelayObservation.ride_id == ride.id)
        .limit(1)
    )

    extracted_count = 0
    if existing_id is None:
        ping_rows = await session.scalars(
            select(LocationPing)
            .where(
                LocationPing.ride_id == ride.id,
                LocationPing.driver_id == ride.driver_id,
            )
            .order_by(LocationPing.recorded_at, LocationPing.id)
        )
        points = [
            GPSObservation(
                lat=ping.lat,
                lng=ping.lng,
                recorded_at=ping.recorded_at,
            )
            for ping in ping_rows
        ]

        candidates = extract_delay_observations(
            points,
            service.edges,
            ride.driver_id,
        )
        extracted_count = len(candidates)

        if candidates:
            session.add_all([
                GPSDelayObservation(
                    ride_id=ride.id,
                    driver_id=observation.driver_id,
                    vehicle_type=vehicle.value,
                    kind=observation.kind.value,
                    junction_id=observation.junction_id,
                    inbound_segment=observation.inbound_segment,
                    outbound_segment=observation.outbound_segment,
                    wait_s=observation.wait_s,
                    observed_at=observation.observed_at,
                )
                for observation in candidates
            ])
            await session.commit()

    # Always refit from the persisted learning window, not only this ride.
    observations = await _observations_for_vehicle(session, vehicle, now)
    service.refresh_delays(observations, now)
    log.info(
        "Refitted GPS delay model for %s using %d observations",
        vehicle.value,
        len(observations),
    )
    return extracted_count


async def restore_delay_models(ctx: AppContext) -> None:
    """Rebuild in-memory delay models from persisted observations at startup."""
    router = ctx.routes.router
    if router is None:
        return

    now = datetime.now(timezone.utc)
    async with ctx.db.sessions() as session:
        for vehicle, service in router.services.items():
            if service.buckets is None:
                continue
            observations = await _observations_for_vehicle(session, vehicle, now)
            service.refresh_delays(observations, now)
            log.info(
                "Restored GPS delay model for %s using %d observations",
                vehicle.value,
                len(observations),
            )
