from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..context import AppContext
from ..deps import get_ctx, get_session
from ..models import OtpCode, Role, User
from ..schemas import OtpRequestIn, OtpRequestOut, OtpVerifyIn, RefreshIn, TokenOut, UserOut
from ..security import decode_token, hash_otp, make_token, new_otp, normalize_phone, otp_matches

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError as e:
        raise HTTPException(422, str(e))


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, phone=u.phone, name=u.name, role=u.role.value, rating=u.rating)


def _tokens(user: User, ctx: AppContext) -> TokenOut:
    return TokenOut(access_token=make_token(user.id, user.role.value, "access", ctx.settings),
                    refresh_token=make_token(user.id, user.role.value, "refresh", ctx.settings),
                    user=user_out(user))


@router.post("/otp/request", response_model=OtpRequestOut)
async def request_otp(body: OtpRequestIn, ctx: AppContext = Depends(get_ctx),
                      session: AsyncSession = Depends(get_session)) -> OtpRequestOut:
    phone = _phone(body.phone)
    code = new_otp(ctx.settings)
    existing = await session.get(OtpCode, phone)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ctx.settings.otp_ttl_seconds)
    if existing:
        existing.code_hash, existing.expires_at, existing.attempts = hash_otp(phone, code, ctx.settings), expires, 0
    else:
        session.add(OtpCode(phone=phone, code_hash=hash_otp(phone, code, ctx.settings), expires_at=expires))
    await session.commit()
    if ctx.settings.is_dev:
        log.info("dev OTP for %s: %s", phone, code)
        return OtpRequestOut(sent=True, expires_in=ctx.settings.otp_ttl_seconds, dev_code=code)
    # Production: send through a DLT-registered SMS provider (MSG91 / Twilio Verify) here.
    raise HTTPException(503, "SMS provider not configured")


@router.post("/otp/verify", response_model=TokenOut)
async def verify_otp(body: OtpVerifyIn, ctx: AppContext = Depends(get_ctx),
                     session: AsyncSession = Depends(get_session)) -> TokenOut:
    phone = _phone(body.phone)
    otp = await session.get(OtpCode, phone)
    if otp is None or otp.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "code expired; request a new one")
    if otp.attempts >= ctx.settings.otp_max_attempts:
        raise HTTPException(429, "too many attempts; request a new code")
    if not otp_matches(phone, body.code, otp.code_hash, ctx.settings):
        otp.attempts += 1
        await session.commit()
        raise HTTPException(401, "wrong code")
    await session.delete(otp)

    user = await session.scalar(select(User).where(User.phone == phone))
    if user is None:
        role = Role.ADMIN if phone in ctx.settings.admin_phones else Role(body.role)
        user = User(phone=phone, role=role)
        session.add(user)
    elif user.role is not Role.ADMIN and user.role.value != body.role:
        await session.commit()
        raise HTTPException(409, f"this number is registered as a {user.role.value}")
    await session.commit()
    return _tokens(user, ctx)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, ctx: AppContext = Depends(get_ctx),
                  session: AsyncSession = Depends(get_session)) -> TokenOut:
    try:
        payload = decode_token(body.refresh_token, "refresh", ctx.settings)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid refresh token")
    user = await session.get(User, payload["sub"])
    if user is None:
        raise HTTPException(401, "account not found")
    return _tokens(user, ctx)
