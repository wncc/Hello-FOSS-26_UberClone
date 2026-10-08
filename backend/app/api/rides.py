from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from matching.geo import haversine_km
from routing import VehicleType

from ..context import AppContext
from ..deps import current_user, get_ctx, get_session, require
from ..errors import DomainError
from ..models import DriverProfile, DriverStatus, Ride, RideStatus, Role, User
from ..schemas import (
    CancelIn, EstimateIn, EstimateOption, EstimateOut, RatingIn, RideCreateIn, RideOut, RouteOut, StartIn,
)
from ..services import rides as svc
from ..services.pricing import fare_paise
from ..services.rides import NO_ROUTE_MESSAGE

router = APIRouter(prefix="/rides", tags=["rides"])
driver_only = require(Role.DRIVER)
NEARBY_KM = 4.0


@router.post("/estimate", response_model=EstimateOut)
async def estimate(body: EstimateIn, ctx: AppContext = Depends(get_ctx), _: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)) -> EstimateOut:
    origin, dest = (body.pickup.lat, body.pickup.lng), (body.drop.lat, body.drop.lng)
    nearby = await _drivers_nearby(session, ctx, origin)
    options = []
    for vehicle in VehicleType:
        route = ctx.routes.estimate(origin, dest, vehicle)
        if route is None:
            continue
        options.append(EstimateOption(vehicle_type=vehicle, fare_paise=fare_paise(vehicle, route.distance_m, route.duration_s),
                                      distance_m=route.distance_m, duration_s=route.duration_s,
                                      drivers_nearby=nearby.get(vehicle.value, 0), route=route.geometry))
    if not options:
        raise DomainError(422, NO_ROUTE_MESSAGE)
    return EstimateOut(options=options)


async def _drivers_nearby(session: AsyncSession, ctx: AppContext, origin) -> dict[str, int]:
    fresh_after = datetime.now(timezone.utc) - timedelta(seconds=ctx.settings.location_stale_seconds)
    counts: dict[str, int] = {}
    for p in await session.scalars(select(DriverProfile).where(
            DriverProfile.is_online.is_(True), DriverProfile.status == DriverStatus.APPROVED,
            DriverProfile.location_at >= fresh_after)):
        if haversine_km(origin, (p.lat, p.lng)) <= NEARBY_KM:
            counts[p.vehicle_type] = counts.get(p.vehicle_type, 0) + 1
    return counts


@router.post("", response_model=RideOut, status_code=201)
async def book(body: RideCreateIn, user: User = Depends(current_user), ctx: AppContext = Depends(get_ctx),
               session: AsyncSession = Depends(get_session)) -> RideOut:
    ride = await svc.create_ride(session, ctx, user, body)
    return await svc.ride_out(session, ride, user)


@router.get("", response_model=list[RideOut])
async def history(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                  limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)) -> list[RideOut]:
    rides = await session.scalars(select(Ride).where(or_(Ride.rider_id == user.id, Ride.driver_id == user.id))
                                  .order_by(Ride.requested_at.desc()).limit(limit).offset(offset))
    return [await svc.ride_out(session, r, user) for r in rides]


@router.get("/active", response_model=RideOut | None)
async def active(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> RideOut | None:
    ride = await svc.active_ride_of(session, user)
    return await svc.ride_out(session, ride, user) if ride else None


@router.get("/{ride_id}", response_model=RideOut)
async def get_ride(ride_id: str, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)) -> RideOut:
    return await svc.ride_out(session, await svc.get_ride_for(session, ride_id, user), user)


@router.get("/{ride_id}/route", response_model=RouteOut)
async def ride_route(ride_id: str, user: User = Depends(current_user), ctx: AppContext = Depends(get_ctx),
                     session: AsyncSession = Depends(get_session)) -> RouteOut:
    """Road geometry to draw: the trip, and the driver's way to the pickup while they're coming."""
    ride = await svc.get_ride_for(session, ride_id, user)
    vehicle = VehicleType(ride.vehicle_type)
    pickup, drop = (ride.pickup_lat, ride.pickup_lng), (ride.drop_lat, ride.drop_lng)
    trip = ctx.routes.estimate(pickup, drop, vehicle)
    approach = None
    if ride.driver_id and ride.status is RideStatus.DRIVER_ASSIGNED:
        profile = await session.get(DriverProfile, ride.driver_id)
        if profile and profile.lat is not None:
            way = ctx.routes.estimate((profile.lat, profile.lng), pickup, vehicle)
            approach = way.geometry if way else None
    return RouteOut(trip=trip.geometry if trip else [pickup, drop], approach=approach)


@router.post("/{ride_id}/accept", status_code=202)
async def accept(ride_id: str, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                 session: AsyncSession = Depends(get_session)) -> dict:
    """Accepted offers are resolved by the next dispatch cycle (nearest acceptor wins);
    the driver gets `ride:confirmed` or `ride:taken`."""
    await svc.approved_driver(session, user)
    await svc.respond_to_offer(session, ctx, ride_id, user, accept=True)
    return {"status": "accepted", "awaiting_confirmation": True}


@router.post("/{ride_id}/reject", status_code=204)
async def reject(ride_id: str, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                 session: AsyncSession = Depends(get_session)) -> None:
    await svc.respond_to_offer(session, ctx, ride_id, user, accept=False)


@router.post("/{ride_id}/arrived", response_model=RideOut)
async def arrived(ride_id: str, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                  session: AsyncSession = Depends(get_session)) -> RideOut:
    return await svc.ride_out(session, await svc.mark_arrived(session, ctx, ride_id, user), user)


@router.post("/{ride_id}/start", response_model=RideOut)
async def start(ride_id: str, body: StartIn, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                session: AsyncSession = Depends(get_session)) -> RideOut:
    return await svc.ride_out(session, await svc.start_ride(session, ctx, ride_id, user, body.pin), user)


@router.post("/{ride_id}/complete", response_model=RideOut)
async def complete(ride_id: str, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                   session: AsyncSession = Depends(get_session)) -> RideOut:
    return await svc.ride_out(session, await svc.complete_ride(session, ctx, ride_id, user), user)


@router.post("/{ride_id}/cancel", response_model=RideOut)
async def cancel(ride_id: str, body: CancelIn, user: User = Depends(current_user), ctx: AppContext = Depends(get_ctx),
                 session: AsyncSession = Depends(get_session)) -> RideOut:
    return await svc.ride_out(session, await svc.cancel_ride(session, ctx, ride_id, user, body.reason), user)


@router.post("/{ride_id}/rating", status_code=201)
async def rate(ride_id: str, body: RatingIn, user: User = Depends(current_user),
               session: AsyncSession = Depends(get_session)) -> dict:
    rating = await svc.rate(session, ride_id, user, body.stars, body.comment)
    return {"id": rating.id, "stars": rating.stars}

