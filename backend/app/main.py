"""FastAPI application.

    uvicorn backend.app.main:app --reload            (from the repo root)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import admin, auth, drivers, realtime, rides, users
from .config import Settings, settings as default_settings
from .context import AppContext
from .db import Database
from .deps import get_ctx
from .errors import DomainError
from .models import Ride
from .services.dispatch import Dispatcher
from .services.realtime import Hub
from .services.routes import RouteService, load_route_service
from fastapi.responses import HTMLResponse
from backend.app.services import rides as ride_svc
from backend.app.deps import get_session
from backend.app.schemas import PublicTrackOut
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, routes: RouteService | None = None) -> FastAPI:
    settings = settings or default_settings
    settings.validate()
    ctx = AppContext(settings=settings, db=Database(settings.database_url), hub=Hub(),
                     routes=routes or RouteService())
    dispatcher = Dispatcher(ctx)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if routes is None and settings.roads_path:
            # Loading a city's road network takes ~20-30 s; done at startup, not at import.
            ctx.routes = await asyncio.to_thread(load_route_service, settings.roads_path)
        # Dev applies migrations at startup; tests use create_all (faster, fresh database each time).
        # Production runs `alembic upgrade head` as a deploy step, so several instances never race on it.
        if settings.env == "dev":
            await ctx.db.migrate()
        elif settings.env == "test":
            await ctx.db.create_all()
        if settings.run_matching_loop:
            dispatcher.start()
        yield
        await dispatcher.stop()
        await ctx.db.dispose()

    app = FastAPI(title="UberClone API", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.state.dispatcher = dispatcher
    app.add_middleware(CORSMiddleware, allow_origins=["*"] if settings.is_dev else [],
                       allow_methods=["*"], allow_headers=["*"])

    PRIVACY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    }

    @app.get("/track/{token}/data", response_model=PublicTrackOut)
    async def public_track_data(token: str, session: AsyncSession = Depends(get_session)):
        """Public JSON endpoint polled by the tracking page every 5s."""
        data = await ride_svc.get_public_tracking_data(session, token)
        return data

    @app.get("/track/{token}", response_class=HTMLResponse)
    async def public_track_page(token: str):
        """Self-contained Leaflet map view for shared trips."""
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <title>Live Trip Tracking | UberClone</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #fff; }}
            #map {{ height: 100vh; width: 100vw; }}
            .card {{ position: absolute; bottom: 20px; left: 20px; right: 20px; background: #1e1e1e; padding: 16px; border-radius: 12px; z-index: 1000; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
            h3 {{ margin: 0 0 8px 0; font-size: 18px; color: #4caf50; }}
            p {{ margin: 4px 0; font-size: 14px; color: #b0b0b0; }}
            .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; background: #333; font-size: 12px; margin-bottom: 8px; }}
        </style>
        </head>
        <body>
        <div id="map"></div>
        <div class="card" id="info-card">
            <span class="badge" id="status-badge">Loading trip status...</span>
            <h3 id="driver-title">Driver: Locating...</h3>
            <p id="vehicle-info">Vehicle: --</p>
            <p id="location-note" style="color: #ff9800; font-size: 12px;"></p>
        </div>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
            const map = L.map('map').setView([19.0760, 72.8777], 13);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                maxZoom: 19,
                attribution: '© OpenStreetMap'
            }}).addTo(map);

            let marker = null;

            async function pollData() {{
                try {{
                    const res = await fetch('/track/{token}/data');
                    if (res.status === 410) {{
                        document.getElementById('status-badge').innerText = 'TRIP COMPLETED / ENDED';
                        document.getElementById('status-badge').style.background = '#d32f2f';
                        clearInterval(pollInterval);
                        return;
                    }}
                    if (!res.ok) return;
                    const data = await res.json();
                    
                    document.getElementById('status-badge').innerText = 'Status: ' + data.status.toUpperCase();
                    document.getElementById('driver-title').innerText = data.driver_name ? 'Driver: ' + data.driver_name : 'Waiting for driver assignment...';
                    document.getElementById('vehicle-info').innerText = data.vehicle_number ? `Vehicle: ${{data.vehicle_number}} (${{data.vehicle_model || data.vehicle_type}})` : '';
                    document.getElementById('location-note').innerText = data.location_note || '';

                    const latlng = [data.driver_lat, data.driver_lng];
                    if (!marker) {{
                        marker = L.marker(latlng).addTo(map);
                        map.setView(latlng, 15);
                    }} else {{
                        marker.setLatLng(latlng);
                    }}
                }} catch (e) {{
                    console.error('Polling error:', e);
                }}
            }}

            pollData();
            const pollInterval = setInterval(pollData, 5000);
        </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, headers=PRIVACY_HEADERS)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    for module in (auth, users, drivers, rides, admin, realtime):
        app.include_router(module.router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/dev/dispatch/tick", tags=["dev"])
    async def dispatch_tick(c: AppContext = Depends(get_ctx)) -> dict:
        """Run one matching cycle now (dev/test only; production relies on the loop)."""
        if not c.settings.is_dev:
            raise HTTPException(404)
        return await dispatcher.tick()

    @app.get("/dev/rides/{ride_id}/pin", tags=["dev"])
    async def dev_ride_pin(ride_id: str, c: AppContext = Depends(get_ctx)) -> dict:
        """The ride PIN, so the simulated driver can run a demo without typing (dev/test only)."""
        if not c.settings.is_dev:
            raise HTTPException(404)
        async with c.db.sessions() as session:
            ride = await session.get(Ride, ride_id)
            if ride is None:
                raise HTTPException(404)
            return {"pin": ride.pin}

    return app


app = create_app()
