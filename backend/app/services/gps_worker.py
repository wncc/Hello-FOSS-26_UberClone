"""Persist validated GPS evidence and refresh live routing telemetry."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from routing import VehicleType
from routing.map_matching import SegmentIndex

from ..context import AppContext
from ..models import (
    GPSProcessedRide,
    GPSRoadSpeedSample,
    GPSRoadExposure,
    Ride,
    RideStatus,
)
from .gps_learning import (
    learn_ride_speeds,
    load_phase_pings,
    load_planned_segments,
    pings_to_observations,
    validated_ride_exposures,
)
from .gps_preview import load_speed_samples, load_exposures

log = logging.getLogger(__name__)

MAX_RIDES_PER_TICK = 100
PHASE = "trip"
MAX_ATTEMPTS = 5
RETRY_BASE_S = 60.0
RETRY_MAX_S = 3600.0

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

class GPSLearningWorker:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # ride_id -> (failed attempts, do not retry before)
        self._failures: dict[str, tuple[int, datetime]] = {}
        self._indexes: dict[VehicleType, tuple[object, SegmentIndex]] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                stats = await self.tick()
                log.info("GPS learning cycle: %s", stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("GPS learning cycle failed")

            await asyncio.sleep(
                self.ctx.settings.gps_learning_tick_seconds
            )

    async def _index_for(self, vehicle, service) -> SegmentIndex:
        cached = self._indexes.get(vehicle)
        if cached is None or cached[0] is not service.edges:
            index = await asyncio.to_thread(SegmentIndex, service.edges)
            cached = (service.edges, index)
            self._indexes[vehicle] = cached
        return cached[1]

    async def tick(
        self,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Persist validated candidates and refresh live routing telemetry."""
        async with self._lock:
            stats = {
                "rides_processed": 0,
                "speed_samples": 0,
                "rides_failed": 0,
            }

            router = self.ctx.routes.router
            if router is None:
                return stats

            now = _as_utc(now or datetime.now(timezone.utc))

            blocked = [
                ride_id
                for ride_id, (attempts, retry_at) in self._failures.items()
                if attempts >= MAX_ATTEMPTS or retry_at > now
            ]

            # Catch up on unprocessed completed rides, even after downtime.
            async with self.ctx.db.sessions() as session:
                processed = (
                    select(GPSProcessedRide.id)
                    .where(
                        GPSProcessedRide.ride_id == Ride.id,
                        GPSProcessedRide.phase == PHASE,
                    )
                    .exists()
                )

                result = await session.execute(
                    select(Ride)
                    .where(
                        Ride.status == RideStatus.COMPLETED,
                        Ride.completed_at <= now,
                        Ride.driver_id.is_not(None),
                        Ride.vehicle_type.in_(
                            [vehicle.value for vehicle in router.services]
                        ),
                        ~processed,
                        *([Ride.id.not_in(blocked)] if blocked else []),
                    )
                    .order_by(Ride.completed_at, Ride.id)
                    .limit(MAX_RIDES_PER_TICK)
                )

                rides = list(result.scalars().all())

            for ride in rides:
                try:
                    vehicle = VehicleType(ride.vehicle_type)
                    service = router.services.get(vehicle)

                    if service is None:
                        continue

                    index = await self._index_for(vehicle, service)

                    # One transaction per ride: samples and processed
                    # marker are committed together.
                    async with self.ctx.db.sessions() as session:
                        async with session.begin():
                            already_processed = await session.scalar(
                                select(GPSProcessedRide.id).where(
                                    GPSProcessedRide.ride_id == ride.id,
                                    GPSProcessedRide.phase == PHASE,
                                )
                            )

                            if already_processed is not None:
                                continue

                            samples = await learn_ride_speeds(
                                session,
                                ride.driver_id,
                                ride.id,
                                service.edges,
                                vehicle,
                                phase=PHASE,
                                index=index,
                            )

                            for sample in samples:
                                session.add(
                                    GPSRoadSpeedSample(
                                        ride_id=ride.id,
                                        driver_id=ride.driver_id,
                                        segment_id=sample.segment_id,
                                        vehicle_type=vehicle.value,
                                        speed_kmh=sample.speed_kmh,
                                        observed_at=sample.observed_at,
                                    )
                                )

                            # Only persist GPS-verified followed segments.
                            # A nearest-road mismatch alone cannot prove
                            # intentional road avoidance.
                            planned = await load_planned_segments(
                                session, ride.driver_id, ride.id, PHASE,
                            )
                            pings = await load_phase_pings(
                                session, ride.driver_id, ride.id, PHASE,
                            ) if planned else []

                            exposures = await asyncio.to_thread(
                                validated_ride_exposures,
                                pings_to_observations(pings),
                                planned,
                                service.edges,
                                ride.driver_id,
                                ride.id,
                                vehicle,
                                index=index,
                            ) if pings else []

                            seen_segments = set()

                            for exposure in exposures:
                                if exposure.segment_id not in service.edges:
                                    continue
                                if exposure.segment_id in seen_segments:
                                    continue

                                seen_segments.add(exposure.segment_id)

                                session.add(
                                    GPSRoadExposure(
                                        ride_id=ride.id,
                                        driver_id=ride.driver_id,
                                        phase=PHASE,
                                        segment_id=exposure.segment_id,
                                        vehicle_type=vehicle.value,
                                        followed=exposure.followed,
                                        observed_at=exposure.observed_at,
                                    )
                                )

                            session.add(
                                GPSProcessedRide(
                                    ride_id=ride.id,
                                    driver_id=ride.driver_id,
                                    phase=PHASE,
                                    vehicle_type=vehicle.value,
                                    sample_count=len(samples),
                                    processed_at=now,
                                )
                            )

                    stats["rides_processed"] += 1
                    stats["speed_samples"] += len(samples)
                    self._failures.pop(ride.id, None)

                except IntegrityError:
                    # A concurrent worker may have inserted the
                    # same processed-ride marker first.
                    log.info(
                        "GPS learning already recorded for ride %s",
                        ride.id,
                    )

                except asyncio.CancelledError:
                    raise

                except Exception:
                    stats["rides_failed"] += 1
                    attempts = self._failures.get(ride.id, (0, now))[0] + 1
                    delay = min(
                        RETRY_BASE_S * 2 ** (attempts - 1), RETRY_MAX_S
                    )
                    self._failures[ride.id] = (
                        attempts,
                        now + timedelta(seconds=delay),
                    )
                    log.exception(
                        "GPS learning failed for ride %s (attempt %d/%d)",
                        ride.id, attempts, MAX_ATTEMPTS,
                    )

            # Apply recent persisted evidence to each vehicle service.
            async with self.ctx.db.sessions() as session:
                speed_samples = await load_speed_samples(session, now)
                exposures = await load_exposures(session, now)

            for vehicle, service in router.services.items():
                window_days = getattr(
                    getattr(service, "policy", None),
                    "window_days",
                    60.0,
                )
                cutoff = now - timedelta(days=window_days)

                valid_speeds = []
                for sample in speed_samples:
                    observed_at = _as_utc(sample.observed_at)

                    if (
                        sample.vehicle != vehicle
                        or sample.segment_id not in service.edges
                        or not cutoff <= observed_at <= now
                        or not math.isfinite(sample.speed_kmh)
                        or not 0 < sample.speed_kmh <= 130
                    ):
                        continue

                    valid_speeds.append(
                        replace(sample, observed_at=observed_at)
                    )

                valid_exposures = []
                for exposure in exposures:
                    observed_at = _as_utc(exposure.observed_at)

                    if (
                        exposure.vehicle != vehicle
                        or exposure.segment_id not in service.edges
                        or not cutoff <= observed_at <= now
                    ):
                        continue

                    valid_exposures.append(
                        replace(exposure, observed_at=observed_at)
                    )

                if valid_speeds or valid_exposures:
                    service.refresh_telemetry(
                        valid_speeds,
                        valid_exposures,
                        now,
                    )

            return stats
