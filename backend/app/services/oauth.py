"""OAuth sign-in (Google, Microsoft) — the authorization-code flow.

Design constraints, in order:

1. **No provider credentials, no surface.** Until the client id/secret are
   configured, `/oauth/{provider}/start` answers 503 with instructions and the
   frontend hides the button. Nothing here half-works.
2. **State is stateless.** The `state` parameter is an HMAC-signed
   `nonce.timestamp.provider` token validated on return (signature + 10-minute
   age + provider match) — no Redis dependency on the login path, and CSRF on
   the callback is still ruled out. The one thing this doesn't stop is a
   replay INSIDE the 10-minute window, which also requires a captured
   authorization code — acceptable for V1 and documented here on purpose.
3. **The provider vouches for the email.** Accounts created via OAuth are
   marked verified; an EXISTING password account with the same email is
   logged in (not duplicated) — the provider proved mailbox ownership, which
   is exactly what our own verification email proves.

Hotmail/Outlook note: personal Microsoft accounts (hotmail.com, outlook.com,
live.com) sign in through the same Microsoft identity platform — the
`consumers` tenant endpoint below covers them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import httpx
import structlog

from app.core.config import settings
from app.core.errors import Unauthorized, ValidationError

log = structlog.get_logger(__name__)

STATE_TTL_S = 600


@dataclass(frozen=True, slots=True)
class Provider:
    key: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str

    @property
    def client_id(self) -> str:
        return getattr(settings, f"{self.key.upper()}_CLIENT_ID", "")

    @property
    def client_secret(self) -> str:
        return getattr(settings, f"{self.key.upper()}_CLIENT_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        key="google",
        label="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
    ),
    # `consumers` = personal Microsoft accounts: hotmail.com, outlook.com, live.com.
    "microsoft": Provider(
        key="microsoft",
        label="Microsoft",
        authorize_url="https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        scope="openid email profile",
    ),
}


def get_provider(key: str) -> Provider:
    provider = PROVIDERS.get(key)
    if provider is None:
        raise ValidationError(f"Unknown sign-in provider '{key}'.")
    return provider


def redirect_uri(provider: Provider) -> str:
    return f"{settings.OAUTH_CALLBACK_BASE}/api/v1/auth/oauth/{provider.key}/callback"


# ── Signed state ──────────────────────────────────────────────────────────────


def _sign(payload: str) -> str:
    mac = hmac.new(settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def make_state(provider_key: str) -> str:
    payload = f"{secrets.token_urlsafe(16)}.{int(time.time())}.{provider_key}"
    return f"{payload}.{_sign(payload)}"


def check_state(state: str, provider_key: str) -> None:
    """Raises Unauthorized unless `state` is ours, fresh, and for this provider."""
    parts = (state or "").rsplit(".", 1)
    if len(parts) != 2 or not hmac.compare_digest(_sign(parts[0]), parts[1]):
        raise Unauthorized("The sign-in attempt could not be validated. Try again.")
    fields = parts[0].split(".")
    if len(fields) != 3 or fields[2] != provider_key:
        raise Unauthorized("The sign-in attempt could not be validated. Try again.")
    try:
        issued = int(fields[1])
    except ValueError as exc:
        raise Unauthorized("The sign-in attempt could not be validated. Try again.") from exc
    if time.time() - issued > STATE_TTL_S:
        raise Unauthorized("That sign-in attempt expired. Start again.")


# ── Provider round-trips ──────────────────────────────────────────────────────


async def exchange_code(provider: Provider, code: str) -> dict:
    """authorization code → {email, name}. Raises Unauthorized on any refusal."""
    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            provider.token_url,
            data={
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(provider),
            },
        )
        if token_res.status_code != 200:
            log.warning(
                "oauth_token_exchange_failed",
                provider=provider.key,
                status=token_res.status_code,
                body=token_res.text[:200],
            )
            raise Unauthorized(f"{provider.label} rejected the sign-in. Try again.")
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise Unauthorized(f"{provider.label} rejected the sign-in. Try again.")

        info_res = await client.get(
            provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
        )
        if info_res.status_code != 200:
            raise Unauthorized(f"Couldn't read your {provider.label} profile. Try again.")
        info = info_res.json()

    email = (info.get("email") or "").strip().lower()
    if not email:
        raise Unauthorized(
            f"Your {provider.label} account shared no email address — grant the "
            "email permission or sign up with email instead."
        )
    return {"email": email, "name": info.get("name") or email.split("@")[0]}
