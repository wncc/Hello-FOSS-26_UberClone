import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import RideStatus
from app.services.rides import start_ride


def run_start(flag):
    ride = SimpleNamespace(
        id="r1", driver_id="d1", rider_id="u1", pin="1234",
        status=RideStatus.DRIVER_ARRIVED, vehicle_type="car",
        pickup_lat=19.0, pickup_lng=72.0, drop_lat=19.1, drop_lng=72.1,
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=ride)
    session.commit = AsyncMock()
    ctx = SimpleNamespace(
        settings=SimpleNamespace(run_gps_learning_loop=flag),
        routes=SimpleNamespace(
            estimate=MagicMock(return_value=SimpleNamespace(segment_ids=["a"]))
        ),
        hub=SimpleNamespace(send=AsyncMock()),
    )

    async def scenario():
        with patch("app.services.rides.ride_summary", return_value={}):
            await start_ride(session, ctx, "r1", SimpleNamespace(id="d1"), "1234")

    asyncio.run(scenario())
    return ctx, session


def test_start_ride_skips_route_planning_when_learning_off():
    ctx, session = run_start(False)
    ctx.routes.estimate.assert_not_called()
    session.add.assert_not_called()


def test_start_ride_saves_planned_route_when_learning_on():
    ctx, session = run_start(True)
    ctx.routes.estimate.assert_called_once()
    session.add.assert_called_once()