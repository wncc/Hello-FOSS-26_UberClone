"""Settings from environment variables (12-factor). Defaults are for local development."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


DEV_SECRET = "dev-only-secret-change-me-in-production-0123456789"
DEFAULT_ROADS_PATH = os.path.join("data", "roads.pkl")


def _roads_path() -> str | None:
    value = os.environ.get("ROADS_PATH", DEFAULT_ROADS_PATH if os.path.exists(DEFAULT_ROADS_PATH) else "")
    return None if value.strip().lower() in ("", "none", "off") else value


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "dev"))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./uberclone.db"))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", DEV_SECRET))
    access_token_minutes: int = field(default_factory=lambda: int(os.environ.get("ACCESS_TOKEN_MINUTES", "60")))
    refresh_token_days: int = field(default_factory=lambda: int(os.environ.get("REFRESH_TOKEN_DAYS", "30")))
    # In dev/test the OTP is fixed and no SMS is sent. In prod an SMS provider must be configured.
    dev_otp: str = field(default_factory=lambda: os.environ.get("DEV_OTP", "123456"))
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    auto_approve_drivers: bool = field(default_factory=lambda: _bool("AUTO_APPROVE_DRIVERS", True))
    run_matching_loop: bool = field(default_factory=lambda: _bool("RUN_MATCHING_LOOP", True))
    matching_tick_seconds: float = 3.0
    ping_timeout_seconds: float = 20.0         # driver must answer a ping within this
    admin_phones: tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in os.environ.get("ADMIN_PHONES", "").split(",") if p.strip()))
    search_timeout_seconds: int = 180          # no driver found -> ride becomes no_drivers
    location_stale_seconds: int = 60           # drivers silent for longer are not matched
    # Road network from routing.osm_import. Defaults to data/roads.pkl when present; ROADS_PATH=none disables it.
    roads_path: str | None = field(default_factory=lambda: _roads_path())
    city_timezone: str = "IST"
    surge_enabled: bool = field(
        default_factory=lambda: _bool("SURGE_ENABLED", False)
    )
    surge_max_multiplier: float = field(
        default_factory=lambda: float(os.environ.get("SURGE_MAX_MULTIPLIER", "2.0"))
    )
    surge_zone_degrees: float = field(
        default_factory=lambda: float(os.environ.get("SURGE_ZONE_DEGREES", "0.01"))
    )
    surge_sensitivity: float = field(
        default_factory=lambda: float(os.environ.get("SURGE_SENSITIVITY", "0.5"))
    )
    surge_smoothing_alpha: float = field(
        default_factory=lambda: float(os.environ.get("SURGE_SMOOTHING_ALPHA", "0.5"))
    )
    surge_refresh_seconds: int = field(
        default_factory=lambda: int(os.environ.get("SURGE_REFRESH_SECONDS", "60"))
    )

    @property
    def is_dev(self) -> bool:
        return self.env in ("dev", "test")

    def validate(self) -> None:
        if not self.is_dev and self.jwt_secret == DEV_SECRET:
            raise RuntimeError("JWT_SECRET must be set outside dev/test")
        if not 1.0 <= self.surge_max_multiplier <= 2.0:
            raise ValueError("SURGE_MAX_MULTIPLIER must be between 1.0 and 2.0")
        if self.surge_zone_degrees <= 0:
            raise ValueError("SURGE_ZONE_DEGREES must be positive")
        if not 0 < self.surge_smoothing_alpha <= 1:
            raise ValueError("SURGE_SMOOTHING_ALPHA must be in (0, 1]")
        if self.surge_refresh_seconds < 1:
            raise ValueError("SURGE_REFRESH_SECONDS must be at least 1")
        if self.surge_sensitivity < 0:
            raise ValueError("SURGE_SENSITIVITY cannot be negative")


settings = Settings()
