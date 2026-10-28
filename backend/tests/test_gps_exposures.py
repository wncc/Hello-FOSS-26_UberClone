"""Candidate exposure persistence and safe preview checks."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from routing import VehicleType
from routing.models import SegmentExposure
from routing.telemetry import DEFAULT_POLICY
from app.db import Database
from app.models import GPSRoadExposure
from app.services.gps_preview import load_exposures, preview_road_rules

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

def test_exposure_sqlite_roundtrip(tmp_path):
    async def run():
        db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'exp.db').as_posix()}")
        await db.create_all()
        try:
            async with db.sessions() as session:
                async with session.begin():
                    session.add(GPSRoadExposure(
                        ride_id="ride-1", driver_id="driver-1", phase="trip",
                        segment_id="1:2:3", vehicle_type="car", followed=False,
                        observed_at=NOW-timedelta(minutes=1),
                    ))
            async with db.sessions() as session:
                items = await load_exposures(session, NOW)
            assert len(items) == 1
            assert items[0].segment_id == "1:2:3"
            assert items[0].followed is False
            assert items[0].observed_at.tzinfo is not None
        finally:
            await db.dispose()
    asyncio.run(run())

def test_preview_does_not_change_live_rules():
    service = SimpleNamespace(
        profile=SimpleNamespace(vehicle=VehicleType.CAR, priority={}),
        edges={}, buckets=None, policy=DEFAULT_POLICY, speed_policy=None,
        telemetry_rules=[], _without_point_delay=lambda x:x,
    )
    event = SegmentExposure("missing", "driver-1", "ride-1", False, NOW, VehicleType.CAR)
    result = preview_road_rules(service, [], [event], NOW)
    assert result["exposures"] == 0
    assert result["avoidance_rules"] == []
    assert service.telemetry_rules == []
