from __future__ import annotations

import asyncio
import itertools
import os
import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.main import create_app

_phones = itertools.count(9000000001)

# Run the backend tests against PostgreSQL instead of SQLite:
#   TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/uberclone_test python -m pytest backend/tests
# Every test wipes that database, so point it at a throwaway one, never at your dev database
# (that's why this isn't DATABASE_URL).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
on_postgres = TEST_DATABASE_URL.startswith("postgresql")


def empty_database(url: str) -> None:
    """Drop every app table (and Alembic's version table) so the next test starts from nothing."""
    async def run() -> None:
        db = Database(url)
        try:
            await db.drop_all()
            async with db.engine.begin() as conn:
                await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            await db.dispose()
    asyncio.run(run())


def database_url(tmp_path, n: int = 0) -> str:
    """A fresh, empty database for one test: a new SQLite file, or the emptied PostgreSQL test database."""
    if TEST_DATABASE_URL:
        empty_database(TEST_DATABASE_URL)
        return TEST_DATABASE_URL
    return f"sqlite+aiosqlite:///{tmp_path}/test{n}.db"


@pytest.fixture
def make_client(tmp_path):
    """App on a fresh database, with the background matching loop off (tests tick it)."""
    clients = []

    def factory(*, geocoder=None, **overrides) -> TestClient:
        settings = Settings(env="test", database_url=database_url(tmp_path, len(clients)),
                            run_matching_loop=False, roads_path=None, **overrides)
        app = create_app(settings, geocoder=geocoder)
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
