"""Saved places (Home, Work, custom) per rider."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, not_found
from ..models import SavedPlace, User
from ..schemas import SavedPlaceIn, SavedPlaceOut

MAX_SAVED_PLACES = 10


def place_out(p: SavedPlace) -> SavedPlaceOut:
    return SavedPlaceOut(id=p.id, name=p.name, lat=p.lat, lng=p.lng, address=p.address)


async def list_places(session: AsyncSession, user: User) -> list[SavedPlaceOut]:
    rows = (await session.scalars(
        select(SavedPlace)
        .where(SavedPlace.user_id == user.id)
        .order_by(SavedPlace.created_at, SavedPlace.id)
    )).all()
    return [place_out(p) for p in rows]


async def create_place(session: AsyncSession, user: User, body: SavedPlaceIn) -> SavedPlaceOut:
    name = body.name.strip()
    address = body.address.strip()
    if not name or not address:
        raise DomainError(422, "name and address cannot be blank")

    existing = (await session.scalars(
        select(SavedPlace).where(SavedPlace.user_id == user.id)
    )).all()

    for p in existing:
        if p.name.lower() == name.lower():
            raise DomainError(409, f"'{p.name}' is already saved")
        if abs(p.lat - body.lat) < 1e-4 and abs(p.lng - body.lng) < 1e-4:
            raise DomainError(409, f"This location is already saved as '{p.name}'")

    if len(existing) >= MAX_SAVED_PLACES:
        raise DomainError(422, f"at most {MAX_SAVED_PLACES} saved places allowed")

    place = SavedPlace(
        user_id=user.id,
        name=name,
        lat=body.lat,
        lng=body.lng,
        address=address,
    )
    session.add(place)
    await session.commit()
    return place_out(place)


async def delete_place(session: AsyncSession, user: User, place_id: str) -> None:
    place = await session.scalar(
        select(SavedPlace).where(SavedPlace.id == place_id, SavedPlace.user_id == user.id)
    )
    if place is None:
        raise not_found("saved place not found")
    await session.delete(place)
    await session.commit()