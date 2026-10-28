"""Preview GPS road learning without modifying live routing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing import VehicleType
from routing.engine import RoutingService
from routing.models import SpeedSample, SegmentExposure
from routing.speed_model import fit_speed_model
from routing.telemetry import aggregate, derive_rules

from ..models import GPSRoadSpeedSample, GPSRoadExposure


async def load_speed_samples(
    session: AsyncSession,
    now: datetime | None = None,
    window_days: float = 60.0,
) -> list[SpeedSample]:
    """Load recent, valid GPS speed observations."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    result = await session.execute(
        select(GPSRoadSpeedSample).where(
            GPSRoadSpeedSample.observed_at >= cutoff,
            GPSRoadSpeedSample.observed_at <= now,
            GPSRoadSpeedSample.speed_kmh > 0,
            GPSRoadSpeedSample.speed_kmh <= 130,
        )
    )

    samples = []
    seen = set()

    for row in result.scalars():
        try:
            vehicle = VehicleType(row.vehicle_type)
        except ValueError:
            continue

        # At most one observation per ride/road prevents one ride from
        # artificially inflating the evidence weight.
        key = (row.ride_id, row.segment_id, vehicle)
        if key in seen or not math.isfinite(row.speed_kmh):
            continue
        seen.add(key)

        samples.append(
            SpeedSample(
                segment_id=row.segment_id,
                driver_id=row.driver_id,
                trip_id=row.ride_id,
                speed_kmh=row.speed_kmh,
                observed_at=row.observed_at,
                vehicle=vehicle,
            )
        )

    return samples


def preview_speed_rules(
    service: RoutingService,
    samples: list[SpeedSample],
    now: datetime | None = None,
) -> dict:
    """Calculate road health and speed rules without changing the service."""
    now = now or datetime.now(timezone.utc)

    # Enforce the same checks for callers supplying in-memory samples.
    relevant = []
    seen = set()
    for sample in sorted(samples, key=lambda s: s.observed_at):
        key = (sample.trip_id, sample.segment_id, sample.vehicle)
        if (sample.vehicle != service.profile.vehicle
                or sample.segment_id not in service.edges
                or sample.observed_at.tzinfo is None
                or not now - timedelta(days=service.policy.window_days) <= sample.observed_at <= now
                or not math.isfinite(sample.speed_kmh)
                or not 0 < sample.speed_kmh <= 130
                or key in seen):
            continue
        seen.add(key)
        relevant.append(sample)

    if not relevant:
        return {
            "vehicle": service.profile.vehicle.value,
            "samples": 0,
            "roads_analyzed": 0,
            "speed_rules": [],
        }

    adjusted = [
        service._without_point_delay(sample)
        for sample in relevant
    ]

    speed_model = None

    if service.buckets is not None:
        speed_model = fit_speed_model(
            service.edges,
            adjusted,
            now,
            service.buckets,
            policy=service.speed_policy,
        )

    stats = aggregate(
        adjusted,
        [],
        now,
        service.policy,
        speed_model,
    )

    active_rules = {
        rule.rule_id
        for rule in service.telemetry_rules
        if rule.expires_at is None or now < rule.expires_at
    }

    rules, health = derive_rules(
        service.edges,
        stats,
        now,
        active_rules,
        service.policy,
        speed_model,
        priorities=service.profile.priority,
    )

    return {
        "vehicle": service.profile.vehicle.value,
        "samples": len(relevant),
        "roads_analyzed": len(health),
        "speed_rules": [
            {
                "rule_id": rule.rule_id,
                "speed_kmh": rule.value,
                "reason": rule.reason,
            }
            for rule in rules
            if rule.rule_id.startswith("tele.speed.")
        ],
    }



async def load_exposures(
    session: AsyncSession, now: datetime | None = None, window_days: float = 60.0,
) -> list[SegmentExposure]:
    """Load candidate exposure evidence, deduplicated per trip and segment."""
    now = now or datetime.now(timezone.utc)
    if window_days <= 0:
        return []
    rows = await session.scalars(
        select(GPSRoadExposure).where(
            GPSRoadExposure.observed_at >= now - timedelta(days=window_days),
            GPSRoadExposure.observed_at <= now,
        ).order_by(GPSRoadExposure.observed_at, GPSRoadExposure.id)
    )
    seen = set()
    result = []
    for row in rows:
        try:
            vehicle = VehicleType(row.vehicle_type)
        except ValueError:
            continue
        key = (row.ride_id, row.segment_id, vehicle)
        if key in seen:
            continue
        seen.add(key)
        result.append(SegmentExposure(
            segment_id=row.segment_id, driver_id=row.driver_id,
            trip_id=row.ride_id, followed=row.followed,
            observed_at=row.observed_at, vehicle=vehicle,
        ))
    return result


def preview_road_rules(
    service: RoutingService, samples: list[SpeedSample],
    exposures: list[SegmentExposure], now: datetime | None = None,
) -> dict:
    """Preview speed and deviation rules without mutating RoutingService."""
    now = now or datetime.now(timezone.utc)
    window = timedelta(days=service.policy.window_days)
    valid_speeds = []
    speed_seen = set()
    for s in sorted(samples, key=lambda x: x.observed_at):
        key = (s.trip_id, s.segment_id, s.vehicle)
        if (s.vehicle != service.profile.vehicle or s.segment_id not in service.edges
                or s.observed_at.tzinfo is None or not now-window <= s.observed_at <= now
                or not math.isfinite(s.speed_kmh) or not 0 < s.speed_kmh <= 130
                or key in speed_seen):
            continue
        speed_seen.add(key)
        valid_speeds.append(service._without_point_delay(s))

    valid_exposures = []
    exposure_seen = set()
    for e in sorted(exposures, key=lambda x: x.observed_at):
        key = (e.trip_id, e.segment_id, e.vehicle)
        if (e.vehicle != service.profile.vehicle or e.segment_id not in service.edges
                or e.observed_at.tzinfo is None or not now-window <= e.observed_at <= now
                or key in exposure_seen):
            continue
        exposure_seen.add(key)
        valid_exposures.append(e)

    speed_model = (fit_speed_model(service.edges, valid_speeds, now,
                                   service.buckets, policy=service.speed_policy)
                   if service.buckets is not None and valid_speeds else None)
    stats = aggregate(valid_speeds, valid_exposures, now, service.policy, speed_model)
    active = {r.rule_id for r in service.telemetry_rules
              if r.expires_at is None or now < r.expires_at}
    rules, health = derive_rules(service.edges, stats, now, active, service.policy,
                                 speed_model, priorities=service.profile.priority)
    return {
        "vehicle": service.profile.vehicle.value,
        "speed_samples": len(valid_speeds),
        "exposures": len(valid_exposures),
        "roads_analyzed": len(health),
        "speed_rules": [{"rule_id": r.rule_id, "speed_kmh": r.value, "reason": r.reason}
                        for r in rules if r.rule_id.startswith("tele.speed.")],
        "avoidance_rules": [{"rule_id": r.rule_id, "priority_multiplier": r.value,
                              "reason": r.reason}
                             for r in rules if r.rule_id.startswith("tele.dev.")],
    }
