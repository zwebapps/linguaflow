"""Sign in with Google / Microsoft (Hotmail, Outlook, Live) — see services/oauth.py.

Flow: the frontend sends the browser to `/auth/oauth/{provider}/start`, we
redirect to the provider with a signed `state`, the provider calls back to
`/auth/oauth/{provider}/callback`, we exchange the code, find-or-create the
user, and bounce the browser to the frontend's `/oauth/complete` page with a
session token in the URL FRAGMENT (fragments never reach servers or logs).

Callback errors also land on `/oauth/complete`, as `#error=...` — an OAuth
failure must end in the app with a readable message, never on a bare JSON page.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import structlog
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import DbSession
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password
from app.db.models import User
from app.services import oauth as oauth_svc

log = structlog.get_logger(__name__)
router = APIRouter()


class OAuthNotConfigured(AppError):
    code = "oauth_not_configured"
    status_code = 503


class OAuthDenied(AppError):
    code = "oauth_denied"
    status_code = 401


def _provider_or_503(key: str) -> oauth_svc.Provider:
    provider = oauth_svc.get_provider(key)
    if not provider.configured:
        raise OAuthNotConfigured(
            f"{provider.label} sign-in isn't configured on this server yet. "
            f"Set {provider.key.upper()}_CLIENT_ID and "
            f"{provider.key.upper()}_CLIENT_SECRET, or sign up with email."
        )
    return provider


@router.get("/auth/oauth/providers")
async def list_providers() -> list[dict[str, str]]:
    """Which sign-in buttons the frontend should render."""
    return [
        {"id": p.key, "label": p.label}
        for p in oauth_svc.PROVIDERS.values()
        if p.configured
    ]


@router.get("/auth/oauth/{provider_key}/start")
async def oauth_start(provider_key: str) -> RedirectResponse:
    provider = _provider_or_503(provider_key)
    params = {
        "client_id": provider.client_id,
        "redirect_uri": oauth_svc.redirect_uri(provider),
        "response_type": "code",
        "scope": provider.scope,
        "state": oauth_svc.make_state(provider.key),
    }
    return RedirectResponse(f"{provider.authorize_url}?{urlencode(params)}")


@router.get("/auth/oauth/{provider_key}/callback")
async def oauth_callback(
    provider_key: str,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    complete = f"{settings.PUBLIC_APP_URL}/oauth/complete"
    try:
        provider = _provider_or_503(provider_key)
        if error or not code:
            raise OAuthDenied(f"{provider.label} sign-in was cancelled.")
        oauth_svc.check_state(state or "", provider.key)
        profile = await oauth_svc.exchange_code(provider, code)

        user = (
            await db.execute(select(User).where(User.email == profile["email"]))
        ).scalar_one_or_none()
        if user is None:
            # The provider proved mailbox ownership, so the account arrives
            # verified. The random password hash keeps the login form closed
            # for this account until the user sets a password themselves.
            user = User(
                email=profile["email"],
                password_hash=hash_password(f"oauth-{secrets.token_urlsafe(24)}A1!"),
                display_name=profile["name"],
                auth_provider=provider.key,
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            log.info("user_registered_oauth", user_id=str(user.id), provider=provider.key)
        elif user.email_verified_at is None:
            # Same mailbox, proven by the provider — the pending email
            # verification for the password account is satisfied too.
            user.email_verified_at = datetime.now(UTC)
            user.verify_token_hash = None
            user.verify_token_expires = None
            await db.commit()

        token = create_access_token(
            user_id=str(user.id), email=user.email, role=user.role
        )
        return RedirectResponse(f"{complete}#token={quote(token)}")
    except AppError as exc:
        return RedirectResponse(f"{complete}#error={quote(exc.message)}")
    except Exception:
        log.exception("oauth_callback_failed", provider=provider_key)
        return RedirectResponse(
            f"{complete}#error={quote('Sign-in failed. Please try again.')}"
        )
