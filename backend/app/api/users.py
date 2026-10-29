from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_session
from ..models import User
from ..schemas import SavedPlaceIn, SavedPlaceOut, UserOut, UserUpdateIn
from ..services import places
from .auth import user_out

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


@router.patch("", response_model=UserOut)
async def update_me(body: UserUpdateIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)) -> UserOut:
    user.name = body.name.strip()
    await session.commit()
    return user_out(user)


@router.get("/places", response_model=list[SavedPlaceOut])
async def get_my_places(user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)) -> list[SavedPlaceOut]:
    return await places.list_places(session, user)


@router.post("/places", response_model=SavedPlaceOut, status_code=201)
async def add_my_place(body: SavedPlaceIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)) -> SavedPlaceOut:
    return await places.create_place(session, user, body)


@router.delete("/places/{place_id}", status_code=204, response_class=Response)
async def remove_my_place(place_id: str, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)) -> Response:
    await places.delete_place(session, user, place_id)
    return Response(status_code=204)