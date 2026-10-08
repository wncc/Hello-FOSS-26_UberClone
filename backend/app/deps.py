from __future__ import annotations

from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .context import AppContext
from .models import Role, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def get_session(ctx: AppContext = Depends(get_ctx)) -> AsyncIterator[AsyncSession]:
    async with ctx.db.sessions() as session:
        yield session


async def user_from_token(token: str, ctx: AppContext, session: AsyncSession) -> User:
    try:
        payload = decode_token(token, "access", ctx.settings)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    user = await session.get(User, payload["sub"])
    if user is None:
        raise HTTPException(401, "account not found")
    return user


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                       ctx: AppContext = Depends(get_ctx),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None:
        raise HTTPException(401, "missing bearer token")
    return await user_from_token(creds.credentials, ctx, session)


def require(*roles: Role):
    async def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"{' or '.join(r.value for r in roles)} only")
        return user
    return check
