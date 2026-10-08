"""Request / response bodies. Money in paise, distances in metres, durations in seconds."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from routing import VehicleType

from .models import PaymentMethod, PaymentStatus, RideStatus


class OtpRequestIn(BaseModel):
    phone: str


class OtpRequestOut(BaseModel):
    sent: bool
    expires_in: int
    dev_code: str | None = None      # only in dev/test, so apps can log in without SMS


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)
    role: Literal["rider", "driver"] = "rider"   # used when the account is created


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    phone: str
    name: str | None
    role: str
    rating: float | None


class UserUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DriverProfileIn(BaseModel):
    vehicle_type: VehicleType
    vehicle_number: str = Field(min_length=4, max_length=16)
    vehicle_model: str | None = Field(default=None, max_length=60)


class DriverProfileOut(BaseModel):
    user_id: str
    vehicle_type: VehicleType
    vehicle_number: str
    vehicle_model: str | None
    status: str
    is_online: bool


class OnlineIn(BaseModel):
    online: bool


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    heading: float | None = Field(default=None, ge=0, le=360)
    speed_kmh: float | None = Field(default=None, ge=0, le=250)


class PlaceIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=200)


class EstimateIn(BaseModel):
    pickup: PlaceIn
    drop: PlaceIn


class EstimateOption(BaseModel):
    vehicle_type: VehicleType
    fare_paise: int
    distance_m: int
    duration_s: int
    drivers_nearby: int
    route: list[tuple[float, float]] = []      # [lat, lng] along the roads, pickup -> drop


class RouteOut(BaseModel):
    trip: list[tuple[float, float]]            # pickup -> drop
    approach: list[tuple[float, float]] | None = None   # driver -> pickup, while the driver is on the way


class EstimateOut(BaseModel):
    options: list[EstimateOption]


class RideCreateIn(BaseModel):
    pickup: PlaceIn
    drop: PlaceIn
    vehicle_type: VehicleType
    payment_method: PaymentMethod = PaymentMethod.CASH


class PartyOut(BaseModel):
    id: str
    name: str | None
    rating: float | None


class DriverInfoOut(PartyOut):
    vehicle_type: VehicleType
    vehicle_number: str
    vehicle_model: str | None
    lat: float | None
    lng: float | None


class RideOut(BaseModel):
    id: str
    status: RideStatus
    vehicle_type: VehicleType
    pickup: PlaceIn
    drop: PlaceIn
    distance_m: int
    duration_s: int
    fare_estimate_paise: int
    fare_final_paise: int | None
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    pin: str | None = None            # only shown to the rider
    rider: PartyOut | None = None
    driver: DriverInfoOut | None = None
    requested_at: datetime
    assigned_at: datetime | None
    arrived_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: str | None
    cancel_reason: str | None


class StartIn(BaseModel):
    pin: str = Field(min_length=4, max_length=4)


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


TokenOut.model_rebuild()
