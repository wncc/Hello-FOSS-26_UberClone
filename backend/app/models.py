"""Database tables. Money is stored in paise (integer); times in UTC."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, Enum):
    RIDER = "rider"
    DRIVER = "driver"
    ADMIN = "admin"


class DriverStatus(str, Enum):
    PENDING = "pending"        # waiting for admin approval
    APPROVED = "approved"
    SUSPENDED = "suspended"


class RideStatus(str, Enum):
    SEARCHING = "searching"
    DRIVER_ASSIGNED = "driver_assigned"
    DRIVER_ARRIVED = "driver_arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_DRIVERS = "no_drivers"


ACTIVE_RIDE_STATUSES = (RideStatus.SEARCHING, RideStatus.DRIVER_ASSIGNED, RideStatus.DRIVER_ARRIVED,
                        RideStatus.IN_PROGRESS)
DRIVER_BUSY_STATUSES = (RideStatus.DRIVER_ASSIGNED, RideStatus.DRIVER_ARRIVED, RideStatus.IN_PROGRESS)


class OfferStatus(str, Enum):
    PINGED = "pinged"
    ACCEPTED = "accepted"      # driver tapped accept; the next matching cycle picks the winner
    REJECTED = "rejected"
    WON = "won"
    LOST = "lost"              # another driver won
    EXPIRED = "expired"        # ping timed out
    RELEASED = "released"      # ride matched / cancelled before the driver answered


class PaymentMethod(str, Enum):
    CASH = "cash"
    ONLINE = "online"          # Razorpay (phase 4)


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python, whatever the database returns (SQLite drops tzinfo)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def _enum(e: type[Enum]) -> SAEnum:
    return SAEnum(e, values_callable=lambda x: [m.value for m in x], native_enum=False, length=32)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.RIDER)
    rating_sum: Mapped[int] = mapped_column(Integer, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    driver: Mapped["DriverProfile | None"] = relationship(back_populates="user", uselist=False)

    @property
    def rating(self) -> float | None:
        return round(self.rating_sum / self.rating_count, 2) if self.rating_count else None


class OtpCode(Base):
    __tablename__ = "otp_codes"
    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class DriverProfile(Base):
    __tablename__ = "driver_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    vehicle_type: Mapped[str] = mapped_column(String(16))         # routing.VehicleType value
    vehicle_number: Mapped[str] = mapped_column(String(16))
    vehicle_model: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[DriverStatus] = mapped_column(_enum(DriverStatus), default=DriverStatus.PENDING)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    location_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(back_populates="driver")


class Ride(Base):
    __tablename__ = "rides"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    rider_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[RideStatus] = mapped_column(_enum(RideStatus), default=RideStatus.SEARCHING, index=True)

    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lng: Mapped[float] = mapped_column(Float)
    pickup_address: Mapped[str | None] = mapped_column(String(200))
    drop_lat: Mapped[float] = mapped_column(Float)
    drop_lng: Mapped[float] = mapped_column(Float)
    drop_address: Mapped[str | None] = mapped_column(String(200))

    distance_m: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[int] = mapped_column(Integer)
    fare_estimate_paise: Mapped[int] = mapped_column(Integer)
    fare_final_paise: Mapped[int | None] = mapped_column(Integer)
    pin: Mapped[str] = mapped_column(String(4))

    payment_method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod), default=PaymentMethod.CASH)
    payment_status: Mapped[PaymentStatus] = mapped_column(_enum(PaymentStatus), default=PaymentStatus.PENDING)

    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    searching_since: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_by: Mapped[Role | None] = mapped_column(_enum(Role))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))


class RideOffer(Base):
    """A ping sent to one driver for one ride."""
    __tablename__ = "ride_offers"
    __table_args__ = (UniqueConstraint("ride_id", "driver_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OfferStatus] = mapped_column(_enum(OfferStatus), default=OfferStatus.PINGED, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("ride_id", "from_user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id"))
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    stars: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LocationPing(Base):
    """Driver GPS breadcrumbs: input for map matching and routing telemetry (slow / avoided roads)."""
    __tablename__ = "location_pings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    ride_id: Mapped[str | None] = mapped_column(ForeignKey("rides.id"))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
