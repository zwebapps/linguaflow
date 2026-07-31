"""Password hashing + JWT issue/verify.

V1 is local auth. V2 swaps to Supabase Auth: replace ``decode_token`` with JWKS
verification against Supabase and everything downstream is unchanged, because the
rest of the app only ever sees ``TokenClaims``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import Unauthorized

# We call bcrypt directly rather than through passlib: passlib 1.7.4 (unmaintained
# since 2020) crashes against bcrypt 5.x — its backend self-test trips bcrypt's
# 72-byte limit and every hash call fails. bcrypt's own API is small enough that
# the abstraction bought us nothing.

BCRYPT_MAX_BYTES = 72


def hash_password(raw: str) -> str:
    """Hash a password. Raises ValueError if it exceeds bcrypt's hard 72-byte limit."""
    data = raw.encode("utf-8")
    if len(data) > BCRYPT_MAX_BYTES:
        # bcrypt would silently truncate, so two different long passwords could
        # unlock the same account. Reject instead of quietly weakening auth.
        raise ValueError(
            f"password must be at most {BCRYPT_MAX_BYTES} bytes "
            f"(got {len(data)}; note non-ASCII characters use several bytes each)"
        )
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    """Constant-time check. Never raises — a malformed stored hash is just a failure."""
    try:
        data = raw.encode("utf-8")
        if len(data) > BCRYPT_MAX_BYTES:
            return False
        return bcrypt.checkpw(data, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


@dataclass(slots=True)
class TokenClaims:
    user_id: str
    email: str
    role: str


def create_access_token(*, user_id: str, email: str, role: str) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid session. Please sign in again.") from exc

    sub = payload.get("sub")
    if not sub:
        raise Unauthorized("Invalid session token.")
    return TokenClaims(
        user_id=str(sub),
        email=str(payload.get("email") or ""),
        role=str(payload.get("role") or "student"),
    )
