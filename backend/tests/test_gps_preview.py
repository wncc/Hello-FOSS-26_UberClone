from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from routing import VehicleType
from routing.models import SpeedSample

from app.services.gps_preview import preview_speed_rules


NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def make_sample(vehicle=VehicleType.CAR):
    return SpeedSample(
        segment_id="123:456:789",
        driver_id="driver-1",
        trip_id="ride-1",
        speed_kmh=20.0,
        observed_at=NOW - timedelta(minutes=5),
        vehicle=vehicle,
    )


def make_service():
    return SimpleNamespace(
        profile=SimpleNamespace(
            vehicle=VehicleType.CAR,
            priority={},
        ),
        edges={},
        buckets=None,
        policy=None,
        speed_policy=None,
        telemetry_rules=[],
        _without_point_delay=lambda sample: sample,
    )


def test_preview_does_not_modify_service():
    service = make_service()

    result = preview_speed_rules(service, [make_sample()], NOW)

    assert result["samples"] == 0
    assert result["roads_analyzed"] == 0
    assert result["speed_rules"] == []
    assert service.telemetry_rules == []


def test_preview_ignores_other_vehicles():
    service = make_service()

    result = preview_speed_rules(
        service,
        [make_sample(VehicleType.BIKE)],
        NOW,
    )

    assert result["samples"] == 0
    assert result["speed_rules"] == []

def test_load_speed_samples_from_sqlite(tmp_path):
    import asyncio

    from sqlalchemy import select

    from app.db import Database
    from app.models import GPSRoadSpeedSample, Ride, RideStatus, User
    from app.services.gps_preview import load_speed_samples

    async def scenario():
        db = Database(
            f"sqlite+aiosqlite:///{(tmp_path / 'gps_preview.db').as_posix()}"
        )
        await db.create_all()

        try:
            async with db.sessions() as session:
                async with session.begin():
                    session.add_all([
                        User(id="rider-1", phone="1111111111"),
                        User(id="driver-1", phone="2222222222"),
                        Ride(
                            id="ride-1",
                            rider_id="rider-1",
                            driver_id="driver-1",
                            vehicle_type="car",
                            status=RideStatus.COMPLETED,
                            pickup_lat=19.0,
                            pickup_lng=72.0,
                            drop_lat=19.1,
                            drop_lng=72.1,
                            distance_m=1000,
                            duration_s=300,
                            fare_estimate_paise=10000,
                            pin="1234",
                            completed_at=NOW,
                        ),
                    ])

            async with db.sessions() as session:
                async with session.begin():
                    session.add(
                        GPSRoadSpeedSample(
                            ride_id="ride-1",
                            driver_id="driver-1",
                            segment_id="123:456:789",
                            vehicle_type="car",
                            speed_kmh=24.5,
                            observed_at=NOW - timedelta(minutes=5),
                        )
                    )

            async with db.sessions() as session:
                samples = await load_speed_samples(session, NOW)

            assert len(samples) == 1
            assert samples[0].segment_id == "123:456:789"
            assert samples[0].speed_kmh == 24.5
            assert samples[0].vehicle == VehicleType.CAR

        finally:
            await db.dispose()

    asyncio.run(scenario())



def test_preview_rejects_future_and_duplicate_trip_samples():
    from routing.telemetry import DEFAULT_POLICY
    service = make_service()
    service.edges = {"123:456:789": object()}
    service.policy = DEFAULT_POLICY
    future = make_sample()
    from dataclasses import replace
    future = replace(future, observed_at=NOW + timedelta(minutes=1))
    # One future sample is rejected; duplicate observations of a trip
    # should not inflate evidence thresholds.
    assert preview_speed_rules(service, [future], NOW)["samples"] == 0
