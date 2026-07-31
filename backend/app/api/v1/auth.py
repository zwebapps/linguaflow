"""Auth + profile — API_CONTRACT.md §1.

Mounted with NO prefix (see app/api/v1/__init__.py), so every path here is
declared in full: `/auth/register`, `/auth/login`, `/me`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.errors import AppError, Unauthorized, ValidationError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User

log = structlog.get_logger(__name__)

router = APIRouter()

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1"]

# Fields that count as "onboarding" for the purpose of stamping `onboarded_at`.
# `display_name` alone is just a profile edit, not onboarding.
_ONBOARDING_FIELDS = {
    "cefr_level", "goal", "learning_style", "daily_goal_minutes",
    "gloss_langs", "native_language", "target_language",
}


class EmailAlreadyRegistered(AppError):
    """§1: contract says register-with-existing-email is 409, code `validation_error`.

    `errors.ValidationError` hardcodes 422 (the general Pydantic-mismatch case), so
    this is a small dedicated subclass rather than a discrepancy — it keeps the
    contract's documented 409 while reusing the same `validation_error` code.
    """

    code = "validation_error"
    status_code = status.HTTP_409_CONFLICT
    message = "An account with this email already exists."


# ── Request models ────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    # §11: password >= 8 chars. Upper bound is generous — the *byte* limit bcrypt
    # actually enforces (72 bytes) is checked separately below so we can surface a
    # clean message instead of a raw bcrypt crash for e.g. a pasted passphrase.
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PatchMeRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    cefr_level: CefrLevel | None = None
    goal: str | None = Field(default=None, max_length=40)
    learning_style: str | None = Field(default=None, max_length=20)
    daily_goal_minutes: int | None = Field(default=None, ge=1, le=600)
    gloss_langs: list[str] | None = None
    # The language the learner speaks (tutor explains in it) and the one they're
    # learning. Validated against the registry so a typo can't silently produce a
    # prompt asking for a language we can't teach.
    native_language: str | None = Field(default=None, max_length=8)
    target_language: str | None = Field(default=None, max_length=8)

    @field_validator("native_language")
    @classmethod
    def _known_native(cls, v: str | None) -> str | None:
        from app.ai.languages import NATIVE_LANGUAGES

        if v is not None and v.lower() not in NATIVE_LANGUAGES:
            raise ValueError(
                f"unsupported native language '{v}'. "
                f"Supported: {', '.join(sorted(NATIVE_LANGUAGES))}"
            )
        return v.lower() if v else v

    @field_validator("target_language")
    @classmethod
    def _teachable_target(cls, v: str | None) -> str | None:
        from app.ai.languages import TARGET_LANGUAGES, enabled_targets

        if v is None:
            return v
        code = v.lower()
        if code not in TARGET_LANGUAGES:
            raise ValueError(f"unknown target language '{v}'")
        if not TARGET_LANGUAGES[code].fully_supported:
            # Refuse rather than half-teach: without a conjugation engine and a
            # curated dictionary the tutor would confidently invent grammar.
            raise ValueError(
                f"'{TARGET_LANGUAGES[code].name}' is not available yet. "
                f"Currently teachable: {', '.join(t.name for t in enabled_targets())}"
            )
        return code


# ── Response models ───────────────────────────────────────────────────────────


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    cefr_level: str
    onboarded: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    cefr_level: str
    goal: str | None
    learning_style: str | None
    daily_goal_minutes: int
    gloss_langs: list[str]
    native_language: str
    target_language: str
    onboarded: bool


def _auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        cefr_level=user.cefr_level,
        onboarded=user.onboarded_at is not None,
    )


def _me_view(user: User) -> MeResponse:
    return MeResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        cefr_level=user.cefr_level,
        goal=user.goal,
        learning_style=user.learning_style,
        daily_goal_minutes=user.daily_goal_minutes,
        gloss_langs=list(user.gloss_langs or []),
        native_language=user.native_language or 'en',
        target_language=user.target_language or 'de',
        onboarded=user.onboarded_at is not None,
    )


def _hash_password_or_422(raw: str) -> str:
    try:
        return hash_password(raw)
    except ValueError as exc:
        # bcrypt silently truncates past 72 bytes; reject with a message the
        # frontend can render as-is rather than letting the ValueError crash the
        # request into a 500.
        raise ValidationError(
            "Password is too long (max 72 bytes).",
            details=[{"field": "password", "issue": str(exc)}],
        ) from exc


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailAlreadyRegistered()

    password_hash = _hash_password_or_422(payload.password)

    user = User(
        email=email,
        password_hash=password_hash,
        display_name=payload.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log.info("user_registered", user_id=str(user.id))
    token = create_access_token(user_id=str(user.id), email=user.email, role=user.role)
    return TokenResponse(access_token=token, user=_auth_user(user))


@router.post("/auth/login")
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    email = payload.email.strip().lower()

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    # Same message whether the email doesn't exist or the password is wrong —
    # never confirm which half was correct.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise Unauthorized("Invalid email or password.")

    token = create_access_token(user_id=str(user.id), email=user.email, role=user.role)
    return TokenResponse(access_token=token, user=_auth_user(user))


@router.get("/me")
async def get_me(user: CurrentUser) -> MeResponse:
    return _me_view(user)


@router.patch("/me")
async def patch_me(payload: PatchMeRequest, user: CurrentUser, db: DbSession) -> MeResponse:
    updates: dict[str, Any] = payload.model_dump(exclude_unset=True)

    # `exclude_unset` keeps keys explicitly set to null, and cefr_level /
    # daily_goal_minutes are NOT NULL — assigning them None turned a client input
    # mistake into an IntegrityError and a generic 500. Reject it as validation.
    non_nullable = {
        "cefr_level", "daily_goal_minutes", "gloss_langs",
        "native_language", "target_language",
    }
    if nulled := {f for f in non_nullable if f in updates and updates[f] is None}:
        raise ValidationError(
            "These fields cannot be set to null: " + ", ".join(sorted(nulled)) + "."
        )

    for field, value in updates.items():
        setattr(user, field, value)

    if user.onboarded_at is None and _ONBOARDING_FIELDS & updates.keys():
        user.onboarded_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(user)
    return _me_view(user)
