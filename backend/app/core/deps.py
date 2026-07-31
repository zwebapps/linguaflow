"""Shared FastAPI dependencies. Both API tracks import from here."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("Sign in to continue.")
    return token.strip()


async def get_current_user(request: Request, db: DbSession) -> User:
    claims = decode_token(_bearer(request))
    user = await db.get(User, claims.user_id)
    if user is None:
        # Token is validly signed but the account is gone.
        raise Unauthorized("Your account no longer exists.")
    return user


async def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_admin:
        # 403, not 404 — the caller is authenticated, just not permitted.
        raise Forbidden("This area is for administrators.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
