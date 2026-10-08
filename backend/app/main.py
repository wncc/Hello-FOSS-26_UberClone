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
        if settings.is_dev:
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
