from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .config import Settings
from .db import Database
from .services.geocoding import Geocoder
from .services.realtime import Hub
from .services.routes import RouteService


@dataclass
class AppContext:
    settings: Settings
    db: Database
    hub: Hub
    routes: RouteService
    geocoder: Geocoder
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)
