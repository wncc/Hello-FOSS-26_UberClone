# Backend (Phase 1)

FastAPI service for riders, drivers and admins. It runs the ride lifecycle, the matching loop ([MATCHING.md](MATCHING.md)) and real-time events, and uses [routing/](../routing/) for trip and pickup estimates.

## Run

```bash
pip install -r backend/requirements.txt -r requirements.txt
uvicorn backend.app.main:app --reload          # from the repo root; API docs at http://localhost:8000/docs
alembic upgrade head                           # schema migrations (dev startup runs this for you)
python -m pytest                                # all tests (routing, matching, backend)
```

| Env var | Default | Notes |
|---|---|---|
| `ROADS_PATH` | `data/roads.pkl` if present | Road network for routing; `ROADS_PATH=none` turns it off |
| `APP_ENV` | `dev` | `dev` / `test`: fixed OTP, `/dev/dispatch/tick` enabled. `dev` applies migrations at startup, `test` creates tables directly. Anything else = production rules (run `alembic upgrade head` yourself) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./uberclone.db` | Production: `postgresql+asyncpg://user:pass@host/db`. Alembic uses it too |
| `TEST_DATABASE_URL` | — | Tests only: run `backend/tests` on this PostgreSQL database instead of SQLite. **It is wiped by every test** |
| `JWT_SECRET` | dev value | **Required** outside dev / test (startup fails without it) |
| `DEV_OTP` | `123456` | Dev only; returned as `dev_code` so the apps can log in without SMS |
| `ADMIN_PHONES` | — | Comma-separated E.164 numbers that become admins on first login |
| `AUTO_APPROVE_DRIVERS` | `true` | Set `false` to require admin approval |
| `RUN_MATCHING_LOOP` | `true` | The dispatch loop (every 3 s) |

## Changing the database

The schema lives in `backend/app/models.py`; every change to it ships with an Alembic migration in `backend/migrations/versions/`. Run these from the repo root.

**I changed a model, now what?**

1. Edit `backend/app/models.py` (add the column, table or index).
2. Generate a migration: `alembic revision --autogenerate -m "add pickup note to rides"`
3. Read the new file in `backend/migrations/versions/`. Autogenerate is a draft: check every line, and fill in data changes (a default for existing rows, a rename that it saw as drop + add) yourself.
4. Apply it: `alembic upgrade head`, or just restart the backend (dev startup runs it).
5. Run the tests. `test_migrations.py` fails if the models and the migrations disagree, so a forgotten migration is caught there.
6. Commit the migration together with the model change.

| Task | Command |
|---|---|
| Apply everything | `alembic upgrade head` |
| Where am I? | `alembic current` / `alembic history` |
| Undo the last migration | `alembic downgrade -1` |
| See the SQL without running it | `alembic upgrade head --sql` |

- **New columns on existing tables** must be nullable or have a `server_default`, or the migration fails on a database that already has rows.
- **SQLite** can't alter columns in place; migrations use batch mode there (set up in `env.py`), which rebuilds the table.
- **Two migrations from the same parent** (two PRs merged in parallel) leave Alembic with two heads. Rebase, then point your migration's `down_revision` at the newest one (`alembic heads` lists them).
- **A database from before migrations** (created by the old `create_all`): delete `uberclone.db` once. The backend tells you this at startup.
- **Production:** run `alembic upgrade head` as a deploy step before starting the new version; the app doesn't migrate itself outside dev, so several instances never race on it.

**PostgreSQL locally:**

```bash
createdb uberclone && createdb uberclone_test
DATABASE_URL=postgresql+asyncpg://localhost/uberclone alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://localhost/uberclone_test python -m pytest backend/tests
```

**Row locks.** The dispatch cycle selects searching rides with `SELECT … FOR UPDATE SKIP LOCKED`, and cancelling or answering a ping locks the ride first (`with_for_update`). So a ride is never assigned twice or assigned after the rider cancelled, even with several backend instances. SQLite ignores the locks; one process with one dispatch loop doesn't need them.

## Road data (routes that follow the roads)

The backend routes on real roads when `data/roads.pkl` exists, and loads it automatically at startup (about 15–30 s; the console shows `road data ready`). Without it, every route is a straight-line estimate.

Build it once per city from OpenStreetMap. For Mumbai (already built on this machine):

```powershell
curl.exe -L -o data\western-zone-latest.osm.pbf https://download.geofabrik.de/asia/india/western-zone-latest.osm.pbf
python -m routing.osm_import data\western-zone-latest.osm.pbf --out data\roads.pkl --bbox 18.89,72.77,19.30,73.05
```

That's a 221 MB download and about a 5-minute import. Mumbai comes out at roughly 285,000 road segments per vehicle type. A route takes 0.1–1 s, and fare estimates for all three vehicles take about 2 s.

- **Outside the map:** a pickup or drop more than 750 m from a mapped road gets "outside the area we have maps for".
- **Other cities:** use their Geofabrik zone and bounding box.
- **`data/` is git-ignored:** each machine builds its own road file.
- **Pickup times in matching** still use straight-line distance × 1.4, because the Python router is too slow to rank 10 drivers every 3 seconds. GraphHopper would make road-based pickup times affordable.

## API

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/otp/request`, `POST /auth/otp/verify` (role `rider` / `driver` on first login), `POST /auth/refresh` |
| Me | `GET /me`, `PATCH /me` |
| Driver | `PUT /drivers/me` (vehicle), `GET /drivers/me`, `POST /drivers/me/online`, `POST /drivers/me/location`, `GET /drivers/me/offer`, `GET /drivers/me/earnings?days=7` (completed rides per calendar day in IST, today included) |
| Rides | `POST /rides/estimate` (fare + road path per vehicle), `GET /rides/{id}/route` (trip path + driver's path to the pickup), `POST /rides`, `GET /rides`, `GET /rides/active`, `GET /rides/{id}`, then `accept` / `reject` / `arrived` / `start` (PIN) / `complete` / `cancel` / `rating` under `/rides/{id}/` |
| Admin | `GET /admin/drivers?status=`, `POST /admin/drivers/{id}/approve` / `suspend`, `GET /admin/rides` |
| Real-time | `WS /ws?token=<access token>` |

All bodies and responses are in the OpenAPI schema (`/openapi.json`); the apps' API client will be generated from it in phase 2.

**WebSocket events** (`{"event": ..., "data": ...}`):
- Driver receives: `ride:ping` (with `expires_in_s`), `ride:ping_cancelled`, `ride:confirmed`, `ride:taken`, `ride:cancelled`, `ride:completed`
- Rider receives: `ride:driver_assigned`, `driver:location`, `ride:driver_arrived`, `ride:started`, `ride:completed`, `ride:driver_cancelled`, `ride:no_drivers`

Drivers send `{"type": "location", "lat", "lng", "heading", "speed_kmh"}` over the same socket, every 3–5 s while online.

## Rules worth knowing

- **One role per phone number.** The rider and driver apps use separate accounts, like most ride-hailing apps.
- **Accepting a ping isn't instant.** The next dispatch cycle (≤ 3 s) picks the nearest acceptor, as the matching engine was designed. The app shows "confirming…" until `ride:confirmed` or `ride:taken`.
- **Missed pings count as rejections.** A driver who rejects a ride, lets its ping lapse (20 s), or cancels after accepting is never pinged for that ride again.
- **The driver can't see the PIN.** The rider reads the 4-digit PIN out at pickup.
- **Matching filters.** Drivers are only matched while online, approved, not on a trip, and with GPS fresher than 60 s.
- **Search timeout.** A ride still searching after 3 minutes becomes `no_drivers`.
- **Fares are placeholders.** The final fare is the estimate for now (no meter yet). Cash is marked paid on completion; online payment returns 422 until phase 4.
- **GPS breadcrumbs.** Driver positions are stored in `location_pings`, the future input for learning slow and avoided roads.

## Known gaps (tracked in [PLAN.md](PLAN.md))

| Gap | Phase |
|---|---|
| Redis for multi-instance WebSockets | 6 |
| Real SMS (MSG91 with DLT templates), rate limiting on OTP requests | 6 |
| Metered final fare, cancellation fees, Razorpay | 4 |
| Push notifications (driver pings when the app is in the background) | 3 |
