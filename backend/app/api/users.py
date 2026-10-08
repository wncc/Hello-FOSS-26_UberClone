from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_session
from ..models import User
from ..schemas import UserOut, UserUpdateIn
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
