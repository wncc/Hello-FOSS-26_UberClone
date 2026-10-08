from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .db import Database
from .services.realtime import Hub
from .services.routes import RouteService


@dataclass
class AppContext:
    settings: Settings
    db: Database
    hub: Hub
    routes: RouteService
