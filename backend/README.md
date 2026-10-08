# backend/

The FastAPI backend: login, rides, fares, live events, and the dispatch loop that runs the matching engine. Full documentation: [docs/BACKEND.md](../docs/BACKEND.md).

```powershell
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000    # from the repo root; API docs at /docs
python -m pytest backend                                            # backend tests
```

| Path | What it is |
|---|---|
| `app/main.py` | Creates the app: routers, startup (database, road data, dispatch loop), dev-only endpoints |
| `app/config.py` | All settings, read from environment variables |
| `app/models.py` | Database tables: users, OTP codes, driver profiles, rides, ride offers (pings), ratings, GPS pings |
| `app/schemas.py` | Request and response bodies |
| `app/api/` | HTTP routes: `auth`, `users` (`/me`), `drivers`, `rides`, `admin`, `realtime` (WebSocket) |
| `app/services/rides.py` | The ride lifecycle: booking, accept / reject, arrived, PIN start, complete, cancel, rating |
| `app/services/dispatch.py` | The every-3-seconds loop: builds the matching engine's input from the database, applies its decisions, sends events |
| `app/services/pricing.py` | Fare cards (bike / auto / cab) and the fare formula |
| `app/services/routes.py` | Trip distance, time and road geometry from the routing engine (or straight-line without road data) |
| `app/services/realtime.py` | WebSocket hub: sends events to a user's open connections |
| `app/services/locations.py` | Driver GPS: latest position, stored breadcrumbs, forwarding to the rider |
| `app/security.py` | Phone number handling, OTP, JWT tokens |
| `tools/simulate.py` | Simulated driver or rider for testing with one phone (also used by `demo.py`) |
| `tests/` | API tests: a full ride, auth, cancellations, timeouts, WebSocket, admin, road-following routes |
