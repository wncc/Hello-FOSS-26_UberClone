"""Trip lifecycle: booking, driver responses, arrival, PIN start, completion, cancellation, ratings.

    searching -> driver_assigned -> driver_arrived -> in_progress -> completed
        |              |                  |
        +-> no_drivers +---- cancelled ---+     (a driver cancelling sends the ride back to searching)

Matching itself (who gets pinged, who wins) happens in dispatch.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing import VehicleType

from ..context import AppContext
from ..errors import DomainError, conflict, forbidden, not_found
from ..models import (
    ACTIVE_RIDE_STATUSES, DRIVER_BUSY_STATUSES, DriverProfile, DriverStatus, OfferStatus, PaymentMethod,
    PaymentStatus, Rating, Ride, RideOffer, RideStatus, Role, User,
)
from ..schemas import DriverInfoOut, PartyOut, PlaceIn, RideCreateIn, RideOut
from .pricing import fare_paise

NO_ROUTE_MESSAGE = "No road route found. The pickup or drop may be outside the area we have maps for."

CANCELLABLE_BY_RIDER = (RideStatus.SEARCHING, RideStatus.DRIVER_ASSIGNED, RideStatus.DRIVER_ARRIVED)
CANCELLABLE_BY_DRIVER = (RideStatus.DRIVER_ASSIGNED, RideStatus.DRIVER_ARRIVED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Serialization (what each party may see)
# --------------------------------------------------------------------------- #

def _party(user: User | None) -> PartyOut | None:
    return PartyOut(id=user.id, name=user.name, rating=user.rating) if user else None


async def ride_out(session: AsyncSession, ride: Ride, viewer: User) -> RideOut:
    rider = await session.get(User, ride.rider_id)
    driver_info = None
    if ride.driver_id:
        driver = await session.get(User, ride.driver_id)
        profile = await session.get(DriverProfile, ride.driver_id)
        driver_info = DriverInfoOut(
            id=driver.id, name=driver.name, rating=driver.rating, vehicle_type=VehicleType(profile.vehicle_type),
            vehicle_number=profile.vehicle_number, vehicle_model=profile.vehicle_model,
            lat=profile.lat, lng=profile.lng)
    return RideOut(
        id=ride.id, status=ride.status, vehicle_type=VehicleType(ride.vehicle_type),
        pickup=PlaceIn(lat=ride.pickup_lat, lng=ride.pickup_lng, address=ride.pickup_address),
        drop=PlaceIn(lat=ride.drop_lat, lng=ride.drop_lng, address=ride.drop_address),
        distance_m=ride.distance_m, duration_s=ride.duration_s,
        fare_estimate_paise=ride.fare_estimate_paise, fare_final_paise=ride.fare_final_paise,
        payment_method=ride.payment_method, payment_status=ride.payment_status,
        pin=ride.pin if viewer.id == ride.rider_id else None,
        rider=_party(rider), driver=driver_info,
        requested_at=ride.requested_at, assigned_at=ride.assigned_at, arrived_at=ride.arrived_at,
        started_at=ride.started_at, completed_at=ride.completed_at, cancelled_at=ride.cancelled_at,
        cancelled_by=ride.cancelled_by.value if ride.cancelled_by else None, cancel_reason=ride.cancel_reason)


def ride_summary(ride: Ride) -> dict:
    """Payload for ride events (pings etc.); never contains the PIN."""
    return {
        "ride_id": ride.id, "status": ride.status.value, "vehicle_type": ride.vehicle_type,
        "pickup": {"lat": ride.pickup_lat, "lng": ride.pickup_lng, "address": ride.pickup_address},
        "drop": {"lat": ride.drop_lat, "lng": ride.drop_lng, "address": ride.drop_address},
        "distance_m": ride.distance_m, "duration_s": ride.duration_s, "fare_paise": ride.fare_estimate_paise,
        "payment_method": ride.payment_method.value,
    }


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #

async def get_ride_for(session: AsyncSession, ride_id: str, user: User) -> Ride:
    ride = await session.get(Ride, ride_id)
    if ride is None:
        raise not_found("ride")
    if user.role is not Role.ADMIN and user.id not in (ride.rider_id, ride.driver_id):
        offered = await session.scalar(select(RideOffer.id).where(
            RideOffer.ride_id == ride.id, RideOffer.driver_id == user.id))
        if offered is None:
            raise not_found("ride")
    return ride


async def active_ride_of(session: AsyncSession, user: User) -> Ride | None:
    column = Ride.driver_id if user.role is Role.DRIVER else Ride.rider_id
    statuses = DRIVER_BUSY_STATUSES if user.role is Role.DRIVER else ACTIVE_RIDE_STATUSES
    return await session.scalar(select(Ride).where(column == user.id, Ride.status.in_(statuses))
                                .order_by(Ride.requested_at.desc()).limit(1))


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #

async def create_ride(session: AsyncSession, ctx: AppContext, rider: User, req: RideCreateIn) -> Ride:
    if rider.role is not Role.RIDER:
        raise forbidden("only riders can book rides")
    if await active_ride_of(session, rider):
        raise conflict("you already have an active ride")
    if req.payment_method is PaymentMethod.ONLINE:
        raise DomainError(422, "online payments are not available yet; choose cash")
    estimate = ctx.routes.estimate((req.pickup.lat, req.pickup.lng), (req.drop.lat, req.drop.lng), req.vehicle_type)
    if estimate is None:
        raise DomainError(422, NO_ROUTE_MESSAGE)
    if estimate.distance_m < 100:
        raise DomainError(422, "pickup and drop are too close")
    ride = Ride(
        rider_id=rider.id, vehicle_type=req.vehicle_type.value,
        pickup_lat=req.pickup.lat, pickup_lng=req.pickup.lng, pickup_address=req.pickup.address,
        drop_lat=req.drop.lat, drop_lng=req.drop.lng, drop_address=req.drop.address,
        distance_m=estimate.distance_m, duration_s=estimate.duration_s,
        fare_estimate_paise=fare_paise(req.vehicle_type, estimate.distance_m, estimate.duration_s),
        pin=f"{secrets.randbelow(10_000):04d}", payment_method=req.payment_method,
    )
    session.add(ride)
    await session.commit()
    return ride


# --------------------------------------------------------------------------- #
# Driver responses to a ping
# --------------------------------------------------------------------------- #

async def _live_offer(session: AsyncSession, ride_id: str, driver_id: str) -> RideOffer | None:
    return await session.scalar(select(RideOffer).where(
        RideOffer.ride_id == ride_id, RideOffer.driver_id == driver_id,
        RideOffer.status.in_((OfferStatus.PINGED, OfferStatus.ACCEPTED))))


async def respond_to_offer(session: AsyncSession, ctx: AppContext, ride_id: str, driver: User, accept: bool) -> RideOffer:
    offer = await _live_offer(session, ride_id, driver.id)
    if offer is None or offer.status is not OfferStatus.PINGED:
        raise conflict("this ride is no longer offered to you")
    ride = await session.get(Ride, ride_id)
    expired = (_now() - offer.created_at).total_seconds() > ctx.settings.ping_timeout_seconds
    if ride.status is not RideStatus.SEARCHING or expired:
        raise conflict("this ride is no longer offered to you")
    offer.status = OfferStatus.ACCEPTED if accept else OfferStatus.REJECTED
    offer.responded_at = _now()
    await session.commit()
    return offer


# --------------------------------------------------------------------------- #
# Trip progress (driver)
# --------------------------------------------------------------------------- #

async def _driver_ride(session: AsyncSession, ride_id: str, driver: User, allowed: tuple[RideStatus, ...]) -> Ride:
    ride = await session.get(Ride, ride_id)
    if ride is None or ride.driver_id != driver.id:
        raise not_found("ride")
    if ride.status not in allowed:
        raise conflict(f"ride is {ride.status.value}")
    return ride


async def mark_arrived(session: AsyncSession, ctx: AppContext, ride_id: str, driver: User) -> Ride:
    ride = await _driver_ride(session, ride_id, driver, (RideStatus.DRIVER_ASSIGNED,))
    ride.status, ride.arrived_at = RideStatus.DRIVER_ARRIVED, _now()
    await session.commit()
    await ctx.hub.send(ride.rider_id, "ride:driver_arrived", ride_summary(ride))
    return ride


async def start_ride(session: AsyncSession, ctx: AppContext, ride_id: str, driver: User, pin: str) -> Ride:
    ride = await _driver_ride(session, ride_id, driver, (RideStatus.DRIVER_ARRIVED,))
    if not secrets.compare_digest(pin, ride.pin):
        raise DomainError(422, "wrong PIN")
    ride.status, ride.started_at = RideStatus.IN_PROGRESS, _now()
    await session.commit()
    await ctx.hub.send(ride.rider_id, "ride:started", ride_summary(ride))
    return ride


async def complete_ride(session: AsyncSession, ctx: AppContext, ride_id: str, driver: User) -> Ride:
    ride = await _driver_ride(session, ride_id, driver, (RideStatus.IN_PROGRESS,))
    ride.status, ride.completed_at = RideStatus.COMPLETED, _now()
    # Fare = estimate until metered fares (actual GPS distance / waiting time) land.
    ride.fare_final_paise = ride.fare_estimate_paise
    if ride.payment_method is PaymentMethod.CASH:
        ride.payment_status = PaymentStatus.PAID     # the driver collects cash on completion
    await session.commit()
    payload = {**ride_summary(ride), "fare_final_paise": ride.fare_final_paise}
    await ctx.hub.send_many([(ride.rider_id, "ride:completed", payload), (driver.id, "ride:completed", payload)])
    return ride


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #

async def cancel_ride(session: AsyncSession, ctx: AppContext, ride_id: str, user: User, reason: str | None) -> Ride:
    ride = await session.get(Ride, ride_id)
    if ride is None or user.id not in (ride.rider_id, ride.driver_id):
        raise not_found("ride")
    now = _now()

    if user.id == ride.rider_id:
        if ride.status not in CANCELLABLE_BY_RIDER:
            raise conflict(f"ride is {ride.status.value}")
        driver_id = ride.driver_id
        ride.status, ride.cancelled_at, ride.cancelled_by, ride.cancel_reason = \
            RideStatus.CANCELLED, now, Role.RIDER, reason
        released = await _close_offers(session, ride.id, OfferStatus.RELEASED)
        await session.commit()
        events = [(o.driver_id, "ride:ping_cancelled", {"ride_id": ride.id}) for o in released]
        if driver_id:
            events.append((driver_id, "ride:cancelled", {**ride_summary(ride), "by": "rider"}))
        await ctx.hub.send_many(events)
        return ride

    # The assigned driver backs out: the ride goes back to searching, without this driver.
    if ride.status not in CANCELLABLE_BY_DRIVER:
        raise conflict(f"ride is {ride.status.value}")
    offer = await session.scalar(select(RideOffer).where(
        RideOffer.ride_id == ride.id, RideOffer.driver_id == user.id, RideOffer.status == OfferStatus.WON))
    if offer:
        offer.status = OfferStatus.REJECTED     # keeps this driver excluded from re-pings for this ride
    ride.status, ride.driver_id, ride.assigned_at, ride.arrived_at = RideStatus.SEARCHING, None, None, None
    ride.searching_since = now
    await session.commit()
    await ctx.hub.send(ride.rider_id, "ride:driver_cancelled", {**ride_summary(ride), "reason": reason})
    return ride


async def _close_offers(session: AsyncSession, ride_id: str, status: OfferStatus) -> list[RideOffer]:
    offers = list(await session.scalars(select(RideOffer).where(
        RideOffer.ride_id == ride_id, RideOffer.status.in_((OfferStatus.PINGED, OfferStatus.ACCEPTED)))))
    for o in offers:
        o.status = status
    return offers


# --------------------------------------------------------------------------- #
# Ratings
# --------------------------------------------------------------------------- #

async def rate(session: AsyncSession, ride_id: str, user: User, stars: int, comment: str | None) -> Rating:
    ride = await session.get(Ride, ride_id)
    if ride is None or user.id not in (ride.rider_id, ride.driver_id):
        raise not_found("ride")
    if ride.status is not RideStatus.COMPLETED:
        raise conflict("you can rate only completed rides")
    target_id = ride.driver_id if user.id == ride.rider_id else ride.rider_id
    if await session.scalar(select(Rating.id).where(Rating.ride_id == ride.id, Rating.from_user_id == user.id)):
        raise conflict("already rated")
    rating = Rating(ride_id=ride.id, from_user_id=user.id, to_user_id=target_id, stars=stars, comment=comment)
    target = await session.get(User, target_id)
    target.rating_sum += stars
    target.rating_count += 1
    session.add(rating)
    await session.commit()
    return rating


# --------------------------------------------------------------------------- #
# Driver helpers
# --------------------------------------------------------------------------- #

async def approved_driver(session: AsyncSession, user: User) -> DriverProfile:
    if user.role is not Role.DRIVER:
        raise forbidden("drivers only")
    profile = await session.get(DriverProfile, user.id)
    if profile is None:
        raise DomainError(409, "complete your driver profile first")
    if profile.status is not DriverStatus.APPROVED:
        raise forbidden(f"driver account is {profile.status.value}")
    return profile
