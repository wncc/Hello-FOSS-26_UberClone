from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session, require
from ..errors import not_found
from ..models import DriverProfile, DriverStatus, Ride, RideStatus, Role, User
from ..schemas import DriverProfileOut, RideOut
from ..services.rides import ride_out
from .drivers import profile_out

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require(Role.ADMIN)


@router.get("/drivers", response_model=list[DriverProfileOut])
async def list_drivers(status: DriverStatus | None = None, _: User = Depends(admin_only),
                       session: AsyncSession = Depends(get_session)) -> list[DriverProfileOut]:
    query = select(DriverProfile)
    if status:
        query = query.where(DriverProfile.status == status)
    return [profile_out(p) for p in await session.scalars(query)]


async def _set_driver_status(session: AsyncSession, user_id: str, status: DriverStatus) -> DriverProfileOut:
    profile = await session.get(DriverProfile, user_id)
    if profile is None:
        raise not_found("driver")
    profile.status = status
    if status is not DriverStatus.APPROVED:
        profile.is_online = False
    await session.commit()
    return profile_out(profile)


@router.post("/drivers/{user_id}/approve", response_model=DriverProfileOut)
async def approve(user_id: str, _: User = Depends(admin_only), session: AsyncSession = Depends(get_session)):
    return await _set_driver_status(session, user_id, DriverStatus.APPROVED)


@router.post("/drivers/{user_id}/suspend", response_model=DriverProfileOut)
async def suspend(user_id: str, _: User = Depends(admin_only), session: AsyncSession = Depends(get_session)):
    return await _set_driver_status(session, user_id, DriverStatus.SUSPENDED)


@router.get("/rides", response_model=list[RideOut])
async def list_rides(status: RideStatus | None = None, limit: int = Query(50, ge=1, le=200),
                     admin: User = Depends(admin_only), session: AsyncSession = Depends(get_session)) -> list[RideOut]:
    query = select(Ride).order_by(Ride.requested_at.desc()).limit(limit)
    if status:
        query = query.where(Ride.status == status)
    return [await ride_out(session, r, admin) for r in await session.scalars(query)]
