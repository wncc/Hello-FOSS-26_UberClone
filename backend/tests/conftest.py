from __future__ import annotations

import itertools
import random

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

_phones = itertools.count(9000000001)


@pytest.fixture
def make_client(tmp_path):
    """App on a fresh SQLite file, with the background matching loop off (tests tick it)."""
    clients = []

    def factory(**overrides) -> TestClient:
        settings = Settings(env="test", database_url=f"sqlite+aiosqlite:///{tmp_path}/test{len(clients)}.db",
                            run_matching_loop=False, roads_path=None, **overrides)
        app = create_app(settings)
        app.state.dispatcher.rng = random.Random(7)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


class Actor:
    """A logged-in user with convenience calls."""

    def __init__(self, client: TestClient, role: str, phone: str | None = None):
        self.client = client
        self.phone = phone or f"+91{next(_phones)}"
        code = client.post("/auth/otp/request", json={"phone": self.phone}).json()["dev_code"]
        body = client.post("/auth/otp/verify", json={"phone": self.phone, "code": code, "role": role}).json()
        self.token, self.id = body["access_token"], body["user"]["id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(path, json=json or {}, headers=self.headers, **kw)

    def put(self, path, json=None, **kw):
        return self.client.put(path, json=json or {}, headers=self.headers, **kw)

    def events(self, event: str | None = None) -> list[dict]:
        return self.client.app.state.ctx.hub.events_for(self.id, event)


def rider(client) -> Actor:
    r = Actor(client, "rider")
    r.client.patch("/me", json={"name": "Asha"}, headers=r.headers)
    return r


def driver(client, lat: float, lng: float, vehicle: str = "car", number: str | None = None) -> Actor:
    d = Actor(client, "driver")
    d.client.patch("/me", json={"name": f"Driver {d.phone[-4:]}"}, headers=d.headers)
    assert d.put("/drivers/me", {"vehicle_type": vehicle, "vehicle_number": number or f"KA01AB{d.phone[-4:]}",
                                 "vehicle_model": "Test"}).status_code == 200
    assert d.post("/drivers/me/online", {"online": True}).status_code == 200
    assert d.post("/drivers/me/location", {"lat": lat, "lng": lng}).status_code == 204
    return d


def tick(client, now=None) -> dict:
    return client.portal.call(client.app.state.dispatcher.tick, now)
