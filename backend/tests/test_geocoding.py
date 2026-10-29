import asyncio
import time

from .conftest import rider


def wait_for_addresses(r, ride_id, pickup, drop, timeout=2.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        response = r.get(f"/rides/{ride_id}")
        assert response.status_code == 200, response.text
        ride = response.json()

        pickup_ready = pickup is None or ride["pickup"]["address"] == pickup
        drop_ready = drop is None or ride["drop"]["address"] == drop

        if pickup_ready and drop_ready:
            return ride

        time.sleep(0.02)

    raise AssertionError(
        f"Addresses were not resolved in time. Last ride: {ride}"
    )


class FakeGeocoder:
    def __init__(self, *, fail=False, delay=0):
        self.fail = fail
        self.delay = delay
        self.calls = []
        self.closed = False

    async def reverse(self, lat: float, lng: float) -> str | None:
        self.calls.append((lat, lng))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("Fake geocoder failure")
        return f"Address at {lat}, {lng}"

    async def close(self) -> None:
        self.closed = True


def test_missing_addresses_are_resolved(make_client):
    geocoder = FakeGeocoder()
    client = make_client(geocoder=geocoder)
    r = rider(client)

    response = r.post("/rides", {
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "drop": {"lat": 12.9352, "lng": 77.6245},
        "vehicle_type": "car",
    })

    assert response.status_code == 201, response.text
    ride = response.json()
    ride = wait_for_addresses(
        r,
        ride["id"],
        "Address at 12.9716, 77.5946",
        "Address at 12.9352, 77.6245",
    )
    assert len(geocoder.calls) == 2
    assert ride["pickup"]["address"] == "Address at 12.9716, 77.5946"
    assert ride["drop"]["address"] == "Address at 12.9352, 77.6245"


def test_existing_address_is_preserved(make_client):
    geocoder = FakeGeocoder()
    client = make_client(geocoder=geocoder)
    r = rider(client)

    response = r.post("/rides", {
        "pickup": {
            "lat": 12.9716,
            "lng": 77.5946,
            "address": "MG Road",
        },
        "drop": {"lat": 12.9352, "lng": 77.6245},
        "vehicle_type": "car",
    })

    assert response.status_code == 201, response.text
    ride = response.json()
    ride = wait_for_addresses(
        r,
        ride["id"],
        "MG Road",
        "Address at 12.9352, 77.6245",
    )

    assert ride["pickup"]["address"] == "MG Road"
    assert ride["drop"]["address"] == "Address at 12.9352, 77.6245"
    assert geocoder.calls == [(12.9352, 77.6245)]


def test_geocoder_failure_does_not_block_booking(make_client):
    geocoder = FakeGeocoder(fail=True)
    client = make_client(geocoder=geocoder)
    r = rider(client)

    response = r.post("/rides", {
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "drop": {"lat": 12.9352, "lng": 77.6245},
        "vehicle_type": "car",
    })

    assert response.status_code == 201, response.text
    ride = response.json()
    assert ride["pickup"]["address"] is None
    assert ride["drop"]["address"] is None


def test_geocoder_timeout_does_not_block_booking(make_client):
    geocoder = FakeGeocoder(delay=2.0)
    client = make_client(geocoder=geocoder)
    r = rider(client)
    start = time.monotonic()
    response = r.post("/rides", {
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "drop": {"lat": 12.9352, "lng": 77.6245},
        "vehicle_type": "car",
    })
    elapsed = time.monotonic() - start
    assert response.status_code == 201, response.text
    assert elapsed < 1.0, f"Booking took {elapsed:.2f}s"
    ride = response.json()
    assert ride["pickup"]["address"] is None
    assert ride["drop"]["address"] is None
