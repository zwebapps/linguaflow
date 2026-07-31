"""Automated knowledge-base updates: due-feed selection, scheduling, and the
safe-redirect fetch that makes real-world feeds actually ingestable.

Hermetic — HTTP is faked with `respx`; no feed is ever really fetched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.errors import UpstreamError, ValidationError
from app.rag.parsers import _fetch_bytes
from app.services.feeds import _MIN_INTERVAL_MINUTES, _is_due


class _Feed:
    """Minimal FeedSource stand-in — `_is_due` is pure."""

    def __init__(self, *, last_polled_at=None, interval=1440, active=True) -> None:
        self.last_polled_at = last_polled_at
        self.poll_interval_minutes = interval
        self.is_active = active
        self.url = "https://example.com/rss"


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


# ── Due-feed selection ────────────────────────────────────────────────────────


def test_a_never_polled_feed_is_due_immediately() -> None:
    assert _is_due(_Feed(last_polled_at=None), NOW) is True


def test_a_recently_polled_feed_is_not_due() -> None:
    """Restarting the worker must not re-fetch everything."""
    feed = _Feed(last_polled_at=NOW - timedelta(minutes=30), interval=1440)
    assert _is_due(feed, NOW) is False


def test_a_feed_past_its_interval_is_due() -> None:
    feed = _Feed(last_polled_at=NOW - timedelta(minutes=1500), interval=1440)
    assert _is_due(feed, NOW) is True


def test_an_inactive_feed_is_never_due() -> None:
    assert _is_due(_Feed(last_polled_at=None, active=False), NOW) is False


def test_a_politeness_floor_overrides_an_aggressive_interval() -> None:
    """An admin setting 1 minute must not let us hammer a publisher."""
    feed = _Feed(last_polled_at=NOW - timedelta(minutes=2), interval=1)
    assert _is_due(feed, NOW) is False
    just_past = _Feed(
        last_polled_at=NOW - timedelta(minutes=_MIN_INTERVAL_MINUTES + 1), interval=1
    )
    assert _is_due(just_past, NOW) is True


# ── Safe redirect following ───────────────────────────────────────────────────
#
# Refusing redirects outright lost 45 of 86 articles on a live RSS run; following
# them blindly would defeat the SSRF guard. These pin the middle ground.


@respx.mock
async def test_a_normal_redirect_is_followed() -> None:
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/b"})
    )
    respx.get("https://example.com/b").mock(
        return_value=httpx.Response(200, content=b"<html>Guten Tag</html>")
    )
    assert b"Guten Tag" in await _fetch_bytes("https://example.com/a")


@respx.mock
async def test_a_relative_redirect_is_resolved() -> None:
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "/final"})
    )
    respx.get("https://example.com/final").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    assert await _fetch_bytes("https://example.com/a") == b"ok"


@respx.mock
async def test_a_redirect_to_a_private_address_is_still_blocked() -> None:
    """The whole point: every hop is re-validated, not just the first."""
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    with pytest.raises(ValidationError, match="non-public"):
        await _fetch_bytes("https://example.com/a")


@respx.mock
async def test_a_redirect_to_localhost_is_blocked() -> None:
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "http://localhost:8000/admin"})
    )
    with pytest.raises(ValidationError):
        await _fetch_bytes("https://example.com/a")


@respx.mock
async def test_a_redirect_loop_terminates() -> None:
    respx.get("https://example.com/loop").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.com/loop"})
    )
    with pytest.raises(UpstreamError, match="redirects"):
        await _fetch_bytes("https://example.com/loop")


@respx.mock
async def test_a_redirect_without_a_location_header_errors_clearly() -> None:
    respx.get("https://example.com/a").mock(return_value=httpx.Response(301))
    with pytest.raises(UpstreamError, match="Location"):
        await _fetch_bytes("https://example.com/a")


@respx.mock
async def test_an_oversized_body_is_rejected_mid_stream() -> None:
    from app.core.config import settings

    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, content=b"x" * (settings.max_upload_bytes + 10))
    )
    with pytest.raises(ValidationError, match="import limit"):
        await _fetch_bytes("https://example.com/big")


# ── Scheduler loop ────────────────────────────────────────────────────────────


async def test_tick_survives_a_failing_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad cycle must not kill the long-running loop."""
    from app.workers import scheduler

    async def boom(db):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.services.feeds.poll_due_feeds", boom)
    monkeypatch.setattr(scheduler, "_acquire_lock", lambda: _true())
    monkeypatch.setattr(scheduler, "_release_lock", _noop)

    assert await scheduler.tick() == []  # logged, not raised


async def test_tick_is_skipped_when_another_runner_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two replicas polling the same feed would double-ingest."""
    from app.workers import scheduler

    called = {"polled": False}

    async def should_not_run(db):
        called["polled"] = True
        return []

    monkeypatch.setattr("app.services.feeds.poll_due_feeds", should_not_run)
    monkeypatch.setattr(scheduler, "_acquire_lock", lambda: _false())

    assert await scheduler.tick() == []
    assert called["polled"] is False


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False


async def _noop() -> None:
    return None
