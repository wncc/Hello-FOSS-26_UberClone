
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.config import Settings
from backend.app.models import (
    Base,
    DriverProfile,
    DriverStatus,
    Ride,
    RideStatus,
    User,
)
from backend.app.services.surge import SurgePricing


def make_settings(**overrides):
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "jwt_secret": "test-secret",
        "surge_enabled": True,
        "surge_max_multiplier": 2.0,
        "surge_sensitivity": 0.5,
        "surge_smoothing_alpha": 1.0,
        "surge_refresh_seconds": 60,
        "surge_zone_degrees": 0.01,
        "location_stale_seconds": 60,
        "run_matching_loop": False,
        "roads_path": None,
    }
    values.update(overrides)
    return Settings(env="test", **values)


def test_zone_groups_nearby_coordinates():
    surge = SurgePricing(make_settings())
    assert surge.zone(19.001, 72.801) == surge.zone(19.005, 72.805)


def test_zone_separates_different_areas():
    surge = SurgePricing(make_settings())
    assert surge.zone(19.001, 72.801) != surge.zone(19.101, 72.901)


def test_surge_disabled_returns_one_without_database_query():
    surge = SurgePricing(make_settings(surge_enabled=False))
    result = asyncio.run(
        surge.multiplier(None, 19.076, 72.877, "car")
    )
    assert result == 1.0


async def make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def run_async_test(coro):
    async def run():
        engine, sessions = await make_db()
        try:
            async with sessions() as session:
                return await coro(session)
        finally:
            await engine.dispose()

    asyncio.run(run())


async def add_ride(
    session,
    *,
    lat=19.076,
    lng=72.877,
    status=RideStatus.SEARCHING,
    vehicle_type="car",
):
    rider = User(
        phone=f"+91{1000000000 + (await session.scalar(
            __import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(User)
        ) or 0)}",
        role="rider",
        name="Test rider",
    )
    session.add(rider)
    await session.flush()

    ride = Ride(
        rider_id=rider.id,
        vehicle_type=vehicle_type,
        status=status,
        pickup_lat=lat,
        pickup_lng=lng,
        drop_lat=19.2,
        drop_lng=72.9,
        distance_m=5000,
        duration_s=900,
        fare_estimate_paise=10000,
        pin="1234",
    )
    session.add(ride)
    await session.flush()
    return ride


async def add_driver(
    session,
    *,
    lat=19.076,
    lng=72.877,
    online=True,
    status=DriverStatus.APPROVED,
    location_at=None,
):
    count = await session.scalar(
        __import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(User)
    )
    user = User(
        phone=f"+91{2000000000 + (count or 0)}",
        role="driver",
        name="Test driver",
    )
    session.add(user)
    await session.flush()

    profile = DriverProfile(
        user_id=user.id,
        vehicle_type="car",
        vehicle_number=f"TEST{count or 0}",
        status=status,
        is_online=online,
        lat=lat,
        lng=lng,
        location_at=location_at or datetime.now(timezone.utc),
    )
    session.add(profile)
    await session.flush()
    return profile


def test_no_demand_keeps_multiplier_at_one():
    async def check(session):
        surge = SurgePricing(make_settings())
        result = await surge.multiplier(session, 19.076, 72.877, "car")
        assert result == 1.0

    run_async_test(check)


def test_demand_without_available_drivers_hits_cap():
    async def check(session):
        await add_ride(session)
        surge = SurgePricing(make_settings())
        result = await surge.multiplier(session, 19.076, 72.877, "car")
        assert result == 2.0

    run_async_test(check)


def test_demand_supply_ratio_sets_expected_multiplier():
    async def check(session):
        await add_ride(session)
        await add_driver(session)
        await add_driver(session)
        surge = SurgePricing(make_settings())
        result = await surge.multiplier(session, 19.076, 72.877, "car")
        # demand/supply = 1/2; sensitivity = 0.5, so the floor is 1.0.
        assert result == 1.0

    run_async_test(check)


def test_stale_driver_does_not_count_as_supply():
    async def check(session):
        await add_ride(session)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        await add_driver(session, location_at=stale_time)
        surge = SurgePricing(make_settings())
        result = await surge.multiplier(session, 19.076, 72.877, "car")
        assert result == 2.0

    run_async_test(check)


def test_busy_driver_does_not_count_as_supply():
    async def check(session):
        await add_ride(session)
        driver = await add_driver(session)
        busy_ride = await add_ride(session, status=RideStatus.IN_PROGRESS)
        busy_ride.driver_id = driver.user_id
        await session.flush()

        surge = SurgePricing(make_settings())
        result = await surge.multiplier(session, 19.076, 72.877, "car")
        assert result == 2.0

    run_async_test(check)


def test_smoothing_moves_towards_target():
    async def check(session):
        await add_ride(session)
        surge = SurgePricing(make_settings(surge_smoothing_alpha=0.5))
        first = await surge.multiplier(session, 19.076, 72.877, "car")
        assert first == 1.5

        # Force the next call to recalculate rather than use the cache.
        key = (*surge.zone(19.076, 72.877), "car")
        surge._last_refresh[key] = 0
        second = await surge.multiplier(session, 19.076, 72.877, "car")
        assert second == 1.75

    run_async_test(check)


def test_demand_exceeding_supply_increases_multiplier():
    async def check(session):
        for _ in range(3):
            await add_ride(session)
        await add_driver(session)

        surge = SurgePricing(make_settings())
        result = await surge.multiplier(
            session, 19.076, 72.877, "car"
        )

        # 1 + 0.5 * (3 / 1 - 1) = 2.0
        assert result == 2.0

    run_async_test(check)


def test_other_vehicle_type_does_not_count_as_supply():
    async def check(session):
        await add_ride(session, vehicle_type="bike")
        await add_driver(session)  # A car driver

        surge = SurgePricing(make_settings())
        result = await surge.multiplier(
            session, 19.076, 72.877, "bike"
        )

        # Bike demand exists, but no bike driver is available.
        assert result == 2.0

    run_async_test(check)
