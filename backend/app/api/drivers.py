from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from routing import VehicleType

from ..context import AppContext
from ..deps import get_ctx, get_session, require
from ..errors import DomainError
from ..models import DriverProfile, DriverStatus, OfferStatus, Ride, RideOffer, Role, User
from ..schemas import DriverProfileIn, DriverProfileOut, LocationIn, OnlineIn
from ..services.locations import update_location
from ..services.rides import active_ride_of, approved_driver, ride_summary

router = APIRouter(prefix="/drivers/me", tags=["drivers"])
driver_only = require(Role.DRIVER)


def profile_out(p: DriverProfile) -> DriverProfileOut:
    return DriverProfileOut(user_id=p.user_id, vehicle_type=VehicleType(p.vehicle_type),
                            vehicle_number=p.vehicle_number, vehicle_model=p.vehicle_model,
                            status=p.status.value, is_online=p.is_online)


@router.put("", response_model=DriverProfileOut)
async def upsert_profile(body: DriverProfileIn, user: User = Depends(driver_only),
                         ctx: AppContext = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    profile = await session.get(DriverProfile, user.id)
    number = body.vehicle_number.upper().replace(" ", "")
    if profile is None:
        status = DriverStatus.APPROVED if ctx.settings.auto_approve_drivers else DriverStatus.PENDING
        profile = DriverProfile(user_id=user.id, vehicle_type=body.vehicle_type.value, vehicle_number=number,
                                vehicle_model=body.vehicle_model, status=status)
        session.add(profile)
    else:
        if profile.is_online:
            raise DomainError(409, "go offline before changing your vehicle")
        changed = profile.vehicle_type != body.vehicle_type.value or profile.vehicle_number != number
        profile.vehicle_type, profile.vehicle_number, profile.vehicle_model = \
            body.vehicle_type.value, number, body.vehicle_model
        if changed and not ctx.settings.auto_approve_drivers and profile.status is DriverStatus.APPROVED:
            profile.status = DriverStatus.PENDING          # a new vehicle needs re-approval
    await session.commit()
    return profile_out(profile)


@router.get("", response_model=DriverProfileOut)
async def get_profile(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await session.get(DriverProfile, user.id)
    if profile is None:
        raise DomainError(404, "driver profile not found")
    return profile_out(profile)


@router.post("/online", response_model=DriverProfileOut)
async def set_online(body: OnlineIn, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await approved_driver(session, user)
    if not body.online and await active_ride_of(session, user):
        raise DomainError(409, "finish your current ride before going offline")
    profile.is_online = body.online
    await session.commit()
    return profile_out(profile)


@router.post("/location", status_code=204)
async def post_location(body: LocationIn, user: User = Depends(driver_only), ctx: AppContext = Depends(get_ctx),
                        session: AsyncSession = Depends(get_session)) -> None:
    profile = await approved_driver(session, user)
    await update_location(session, ctx, user, profile, body)


@router.get("/offer")
async def current_offer(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)) -> dict | None:
    """The ride this driver is currently pinged for (apps also get it as a `ride:ping` event)."""
    offer = await session.scalar(select(RideOffer).where(
        RideOffer.driver_id == user.id, RideOffer.status == OfferStatus.PINGED)
        .order_by(RideOffer.created_at.desc()).limit(1))
    if offer is None:
        return None
    ride = await session.get(Ride, offer.ride_id)
    return {**ride_summary(ride), "offered_at": offer.created_at.isoformat()}
