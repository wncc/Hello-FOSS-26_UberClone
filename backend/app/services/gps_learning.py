"""Convert stored driver GPS records into candidate road-learning telemetry."""

import asyncio
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing.map_matching import (
    GPSObservation,
    extract_speed_samples,
    group_observations_by_segment,
    match_gps_sequence,
)
from routing.monitoring import detect_exposures
from routing.models import (
    EdgeMeta,
    SegmentExposure,
    SpeedSample,
    VehicleType,
)

from ..models import LocationPing, PlannedRoute, Ride


def pings_to_observations(
    pings: list[LocationPing],
) -> list[GPSObservation]:
    """Convert GPS pings into time-ordered observations."""
    return [
        GPSObservation(
            lat=ping.lat,
            lng=ping.lng,
            recorded_at=ping.recorded_at,
        )
        for ping in sorted(pings, key=lambda p: p.recorded_at)
    ]


async def load_ride_pings(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
) -> list[LocationPing]:
    """Load GPS pings belonging to one driver and ride."""
    result = await session.execute(
        select(LocationPing)
        .where(
            LocationPing.driver_id == driver_id,
            LocationPing.ride_id == ride_id,
        )
        .order_by(LocationPing.recorded_at, LocationPing.id)
    )
    return list(result.scalars().all())


async def load_ride(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
) -> Ride | None:
    """Load a ride only when it belongs to the given driver."""
    result = await session.execute(
        select(Ride).where(
            Ride.id == ride_id,
            Ride.driver_id == driver_id,
        )
    )
    return result.scalar_one_or_none()


def filter_pings_by_phase(
    pings: list[LocationPing],
    phase: str,
    trip_started_at: datetime | None = None,
    *,
    assigned_at: datetime | None = None,
    arrived_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> list[LocationPing]:
    """Return GPS pings inside a completed ride phase."""
    if phase not in ("approach", "trip"):
        raise ValueError("Invalid ride phase")

    if phase == "approach":
        start, end = assigned_at, arrived_at
    else:
        start, end = trip_started_at, completed_at

    if start is None or end is None or end <= start:
        return []

    return [
        ping
        for ping in pings
        if start <= ping.recorded_at <= end
    ]


async def load_phase_pings(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
    phase: str,
) -> list[LocationPing]:
    """Load only GPS pings from a completed ride phase."""
    if phase not in ("approach", "trip"):
        raise ValueError("Invalid ride phase")

    ride = await load_ride(session, driver_id, ride_id)
    if ride is None:
        return []

    if phase == "approach":
        start, end = ride.assigned_at, ride.arrived_at
    else:
        start, end = ride.started_at, ride.completed_at

    if start is None or end is None or end <= start:
        return []

    pings = await load_ride_pings(session, driver_id, ride_id)

    return filter_pings_by_phase(
        pings,
        phase,
        ride.started_at,
        assigned_at=ride.assigned_at,
        arrived_at=ride.arrived_at,
        completed_at=ride.completed_at,
    )


async def learn_ride_speeds(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
    edges: dict[str, EdgeMeta],
    vehicle: VehicleType = VehicleType.CAR,
    *,
    phase: str = "trip",
    index=None
) -> list[SpeedSample]:
    """Extract candidate speed samples from a completed ride phase."""
    pings = await load_phase_pings(
        session, driver_id, ride_id, phase
    )

    if not pings:
        return []

    return await asyncio.to_thread(
        extract_speed_samples,
        pings_to_observations(pings),
        edges,
        driver_id,
        ride_id,
        vehicle,
        index=index,
    )


def learn_ride_exposures(
    observations: list[GPSObservation],
    planned_segments: list[str],
    edges: dict[str, EdgeMeta],
    driver_id: str,
    ride_id: str,
    vehicle: VehicleType = VehicleType.CAR,
) -> list[SegmentExposure]:
    """Compare planned and GPS-matched road segments."""
    if not observations or not planned_segments:
        return []

    actual_segments = match_gps_sequence(observations, edges)

    if not actual_segments:
        return []

    observed_at = max(
        point.recorded_at for point in observations
    )

    return detect_exposures(
        planned=planned_segments,
        actual=actual_segments,
        trip_id=ride_id,
        driver_id=driver_id,
        observed_at=observed_at,
        vehicle=vehicle,
    )


async def load_planned_segments(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
    phase: str,
) -> list[str]:
    """Load planned road segments for one ride phase."""
    if phase not in ("approach", "trip"):
        raise ValueError("phase must be 'approach' or 'trip'")

    result = await session.execute(
        select(PlannedRoute.segment_ids)
        .where(
            PlannedRoute.driver_id == driver_id,
            PlannedRoute.ride_id == ride_id,
            PlannedRoute.phase == phase,
        )
    )

    stored = result.scalar_one_or_none()
    if stored is None:
        return []

    segments = json.loads(stored)

    if not isinstance(segments, list) or not all(
        isinstance(segment, str) for segment in segments
    ):
        raise ValueError("Invalid stored planned route")

    return segments


async def learn_saved_route_exposures(
    session: AsyncSession,
    driver_id: str,
    ride_id: str,
    phase: str,
    edges: dict[str, EdgeMeta],
    vehicle: VehicleType = VehicleType.CAR,
) -> list[SegmentExposure]:
    """Compare a saved route with GPS data from its completed phase."""
    planned = await load_planned_segments(
        session, driver_id, ride_id, phase
    )

    if not planned:
        return []

    pings = await load_phase_pings(
        session, driver_id, ride_id, phase
    )

    if not pings:
        return []

    return learn_ride_exposures(
        pings_to_observations(pings),
        planned,
        edges,
        driver_id,
        ride_id,
        vehicle,
    )


def validated_ride_exposures(
    observations: list[GPSObservation],
    planned_segments: list[str],
    edges: dict[str, EdgeMeta],
    driver_id: str,
    ride_id: str,
    vehicle: VehicleType = VehicleType.CAR,
    index=None
) -> list[SegmentExposure]:
    """Verify followed roads and conservatively detect avoided roads."""
    if len(observations) < 3 or not planned_segments:
        return []

    if any(seg not in edges for seg in planned_segments):
        return []

    points = sorted(
        observations,
        key=lambda p: p.recorded_at,
    )

    # Reject missing or widely separated timestamps.
    if any(
        not 0 < (
            b.recorded_at - a.recorded_at
        ).total_seconds() <= 60
        for a, b in zip(points, points[1:])
    ):
        return []

    actual = match_gps_sequence(points, edges, index=index)

    if not actual or actual[0] != planned_segments[0]:
        return []

    # Preserve existing followed-road behavior.
    prefix = []

    for expected, observed in zip(
        planned_segments, actual
    ):
        if expected != observed:
            break

        prefix.append(expected)

    observed_at = points[-1].recorded_at

    result = [
        SegmentExposure(
            segment_id=seg,
            driver_id=driver_id,
            trip_id=ride_id,
            followed=True,
            observed_at=observed_at,
            vehicle=vehicle,
        )
        for seg in prefix
    ]

    # A mismatch alone is not proof of avoidance.
    if (
        len(prefix) < 2
        or len(prefix) >= len(planned_segments)
    ):
        return result

    # Repeated planned segments make rejoining ambiguous.
    if len(set(planned_segments)) != len(
        planned_segments
    ):
        return result

    groups = group_observations_by_segment(
        points, edges, index=index
    )

    # Reject avoidance evidence if GPS tracking was broken.
    if any(
        seg is None for seg, _ in groups
    ):
        return result

    if not groups:
        return result

    observed_segments = [
        seg for seg, _ in groups
    ]

    # Require the grouped GPS route to match the route sequence.
    if observed_segments != actual:
        return result

    if observed_segments[:len(prefix)] != prefix:
        return result

    # Require at least two GPS observations on each
    # followed segment before considering a deviation.
    if any(
        len(group_points) < 2
        for _, group_points in groups[:len(prefix)]
    ):
        return result

    remaining = groups[len(prefix):]

    # Need two bypass segments and a later rejoin.
    if len(remaining) < 3:
        return result

    rejoin_position = None
    rejoin_plan_index = None

    for i, (seg, _) in enumerate(remaining):
        if seg in planned_segments[len(prefix) + 1:]:
            rejoin_position = i
            rejoin_plan_index = planned_segments.index(
                seg,
                len(prefix) + 1,
            )
            break

    if (
        rejoin_position is None
        or rejoin_position < 2
    ):
        return result

    # Require repeated GPS observations on bypass roads
    # and on the rejoined planned road.
    evidence = remaining[:rejoin_position + 1]

    if any(
        len(group_points) < 2
        for _, group_points in evidence
    ):
        return result

    # Bypass must not include the skipped planned roads.
    skipped = set(
        planned_segments[
            len(prefix):rejoin_plan_index
        ]
    )

    if any(
        seg in skipped
        for seg, _ in remaining[:rejoin_position]
    ):
        return result

    # Check directed connectivity of the alternative path.
    path = (
        [prefix[-1]]
        + [seg for seg, _ in evidence]
    )

    if any(
        edges[a].to_node != edges[b].from_node
        for a, b in zip(path, path[1:])
    ):
        return result

    # Original planned route must also be connected.
    if any(
        edges[a].to_node != edges[b].from_node
        for a, b in zip(
            planned_segments,
            planned_segments[1:],
        )
    ):
        return result

    avoided_segment = planned_segments[len(prefix)]

    result.append(
        SegmentExposure(
            segment_id=avoided_segment,
            driver_id=driver_id,
            trip_id=ride_id,
            followed=False,
            observed_at=observed_at,
            vehicle=vehicle,
        )
    )

    return result
