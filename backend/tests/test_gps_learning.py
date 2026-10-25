from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from backend.app.models import GPSDelayObservation, LocationPing, Ride
from backend.app.services import gps_learning
from backend.tests.conftest import driver, rider
from routing import VehicleType
from routing.delay_model import DelayKind, DelayObservation


def test_gps_delay_persistence_deduplication_and_restore(client, monkeypatch):
    r = rider(client)
    d = driver(client, 12.9726, 77.5946)
    response = r.post(
        "/rides",
        {
            "pickup": {
                "lat": 12.9716,
                "lng": 77.5946,
                "address": "MG Road",
            },
            "drop": {
                "lat": 12.9352,
                "lng": 77.6245,
                "address": "Koramangala",
            },
            "vehicle_type": "car",
        },
    )
    assert response.status_code == 201, response.text
    ride_id = response.json()["id"]

    service = SimpleNamespace(
        buckets=object(),
        edges={},
        refreshed=None,
    )

    def refresh_delays(observations, now):
        service.refreshed = list(observations)

    service.refresh_delays = refresh_delays
    client.app.state.ctx.routes.router = SimpleNamespace(
        services={VehicleType.CAR: service}
    )
    ctx = client.app.state.ctx

    observed_at = datetime.now(timezone.utc)
    candidate = DelayObservation(
        kind=DelayKind.SIGNAL,
        junction_id="J1",
        driver_id=d.id,
        observed_at=observed_at,
        wait_s=45.0,
    )
    extraction_calls = []

    def extract(points, edges, driver_id):
        extraction_calls.append(driver_id)
        return [candidate]

    monkeypatch.setattr(
        gps_learning, "extract_delay_observations", extract
    )

    async def seed_ride_and_pings():
        async with ctx.db.sessions() as session:
            ride = await session.get(Ride, ride_id)
            ride.driver_id = d.id
            session.add_all([
                LocationPing(
                    driver_id=d.id,
                    ride_id=ride_id,
                    lat=12.9716,
                    lng=77.5946,
                    recorded_at=observed_at,
                ),
                LocationPing(
                    driver_id=d.id,
                    ride_id=ride_id,
                    lat=12.9717,
                    lng=77.5947,
                    recorded_at=observed_at,
                ),
            ])
            await session.commit()

    client.portal.call(seed_ride_and_pings)

    async def learn():
        async with ctx.db.sessions() as session:
            ride = await session.get(Ride, ride_id)
            return await gps_learning.learn_from_completed_ride(
                session, ctx, ride
            )

    assert client.portal.call(learn) == 1

    async def read_observations():
        async with ctx.db.sessions() as session:
            return list(await session.scalars(
                select(GPSDelayObservation).where(
                    GPSDelayObservation.ride_id == ride_id
                )
            ))

    rows = client.portal.call(read_observations)
    assert len(rows) == 1
    assert rows[0].kind == DelayKind.SIGNAL.value
    assert rows[0].junction_id == "J1"
    assert rows[0].wait_s == 45.0
    assert rows[0].driver_id == d.id

    # Reprocessing this ride must not extract or save the same observation again.
    assert client.portal.call(learn) == 0
    assert len(client.portal.call(read_observations)) == 1
    assert len(extraction_calls) == 1

    # Startup restoration must rebuild the service from persisted observations.
    client.portal.call(gps_learning.restore_delay_models, ctx)
    assert service.refreshed is not None
    assert len(service.refreshed) == 1
    assert service.refreshed[0].junction_id == "J1"
    assert service.refreshed[0].wait_s == 45.0
