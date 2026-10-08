"""Phone OTP login and JWT access / refresh tokens."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import Settings

INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


def normalize_phone(raw: str) -> str:
    """Accepts 10-digit Indian mobiles with or without +91 / 0 prefix; returns E.164 (+91XXXXXXXXXX)."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        phone = digits
    elif len(digits) == 12 and digits.startswith("91"):
        phone = "+" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        phone = "+91" + digits[1:]
    else:
        phone = "+91" + digits
    if not INDIAN_MOBILE.match(phone):
        raise ValueError("enter a valid Indian mobile number")
    return phone


def new_otp(settings: Settings) -> str:
    return settings.dev_otp if settings.is_dev else f"{secrets.randbelow(10**6):06d}"


def hash_otp(phone: str, code: str, settings: Settings) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(phone: str, code: str, code_hash: str, settings: Settings) -> bool:
    return hmac.compare_digest(hash_otp(phone, code, settings), code_hash)


def make_token(user_id: str, role: str, kind: str, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    ttl = timedelta(minutes=settings.access_token_minutes) if kind == "access" \
        else timedelta(days=settings.refresh_token_days)
    payload = {"sub": user_id, "role": role, "typ": kind, "iat": int(now.timestamp()),
               "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, kind: str, settings: Settings) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != kind:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
