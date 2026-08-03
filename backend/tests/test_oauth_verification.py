"""OAuth sign-in scaffolding + email verification primitives.

What's worth pinning here is the security surface, all of it hermetic:

  * the signed `state` round-trip — forge-resistance, provider binding, expiry
    (CSRF on the OAuth callback is ruled out by exactly these three checks);
  * unconfigured providers answer 503 and are hidden from the button list —
    a half-configured Google button that 500s at the callback is worse than
    no button;
  * verification tokens are stored hashed, so the token-hash helper is the
    contract between issue and verify.
"""

from __future__ import annotations

import time

import pytest

from app.api.v1.auth import _hash_token
from app.api.v1.oauth import _provider_or_503
from app.core.errors import AppError, Unauthorized
from app.services import oauth as oauth_svc

# ── Signed state ──────────────────────────────────────────────────────────────


def test_state_roundtrip_accepts_our_own_token() -> None:
    state = oauth_svc.make_state("google")
    oauth_svc.check_state(state, "google")  # must not raise


def test_state_rejects_a_forged_signature() -> None:
    state = oauth_svc.make_state("google")
    tampered = state[:-4] + ("AAAA" if not state.endswith("AAAA") else "BBBB")
    with pytest.raises(Unauthorized):
        oauth_svc.check_state(tampered, "google")


def test_state_is_bound_to_its_provider() -> None:
    """A Google state replayed on the Microsoft callback must fail."""
    state = oauth_svc.make_state("google")
    with pytest.raises(Unauthorized):
        oauth_svc.check_state(state, "microsoft")


def test_state_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    state = oauth_svc.make_state("google")
    real_time = time.time
    monkeypatch.setattr(
        oauth_svc.time, "time", lambda: real_time() + oauth_svc.STATE_TTL_S + 5
    )
    with pytest.raises(Unauthorized, match="expired"):
        oauth_svc.check_state(state, "google")


def test_state_rejects_garbage() -> None:
    for bad in ("", "abc", "a.b.c.d.e", None):
        with pytest.raises(Unauthorized):
            oauth_svc.check_state(bad or "", "google")


# ── Provider configuration gate ───────────────────────────────────────────────


def test_unconfigured_provider_is_a_503_with_instructions() -> None:
    """Local defaults ship no client ids — the endpoint must say so, not 500."""
    assert not oauth_svc.PROVIDERS["google"].configured
    with pytest.raises(AppError) as exc:
        _provider_or_503("google")
    assert exc.value.status_code == 503
    assert "GOOGLE_CLIENT_ID" in str(exc.value)


def test_unknown_provider_is_a_validation_error() -> None:
    with pytest.raises(AppError):
        _provider_or_503("facebook")


def test_configured_provider_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id-123")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret-456")
    provider = _provider_or_503("google")
    assert provider.configured
    assert oauth_svc.redirect_uri(provider).endswith("/api/v1/auth/oauth/google/callback")


def test_hotmail_lives_on_the_consumers_tenant() -> None:
    """Personal Microsoft accounts (hotmail/outlook/live) use the `consumers`
    endpoints — the org-tenant URL silently rejects them."""
    ms = oauth_svc.PROVIDERS["microsoft"]
    assert "/consumers/" in ms.authorize_url
    assert "/consumers/" in ms.token_url


# ── Verification token hashing ────────────────────────────────────────────────


def test_verification_token_is_stored_hashed_not_plain() -> None:
    token = "some-opaque-token-value-123"
    hashed = _hash_token(token)
    assert hashed != token
    assert len(hashed) == 64  # sha256 hex
    assert _hash_token(token) == hashed  # deterministic: verify can find issue
