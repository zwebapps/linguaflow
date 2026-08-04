"""Redis: response cache, rate limiting, and AI quota counters.

Every function here degrades gracefully — if Redis is down the app keeps serving
(un-cached, un-limited) rather than 500ing. Availability of the tutor beats
perfect enforcement of a dev-time rate limit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import redis.asyncio as aioredis
import structlog

from app.core.config import settings
from app.core.errors import QuotaExceeded, RateLimited

log = structlog.get_logger(__name__)

_client: aioredis.Redis | None = None


def get_client() -> aioredis.Redis | None:
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                # The ingest worker parks on BLPOP for INGEST_BLOCK_SECONDS. With
                # no socket read timeout redis-py waits forever on a connection a
                # managed provider has quietly dropped; with one SHORTER than the
                # block it tears down every healthy wait ("Timeout reading from
                # <host>"). So: comfortably longer than the longest blocking call.
                socket_timeout=settings.INGEST_BLOCK_SECONDS + 15,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
        except Exception as exc:  # pragma: no cover
            log.warning("redis_unavailable", error=str(exc))
            return None
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping() -> bool:
    c = get_client()
    if c is None:
        return False
    try:
        return bool(await c.ping())
    except Exception:
        return False


async def enforce_rate_limit(
    user_id: str, bucket: str = "ai", limit: int | None = None
) -> None:
    """Fixed-window limiter. Raises RateLimited with a Retry-After hint."""
    c = get_client()
    if c is None:
        return
    limit = limit or settings.RATE_LIMIT_PER_MINUTE
    now = datetime.now(UTC)
    key = f"rl:{bucket}:{user_id}:{now.strftime('%Y%m%d%H%M')}"
    try:
        count = await c.incr(key)
        if count == 1:
            await c.expire(key, 60)
        if count > limit:
            raise RateLimited(retry_after=max(1, 60 - now.second))
    except RateLimited:
        raise
    except Exception as exc:
        log.warning("rate_limit_check_failed", error=str(exc))


async def enforce_monthly_quota(user_id: str, limit: int | None = None) -> None:
    """Caps free-tier AI calls so a runaway loop can't drain the OpenRouter budget."""
    c = get_client()
    if c is None:
        return
    limit = limit or settings.FREE_MONTHLY_AI_CALLS
    key = f"quota:{user_id}:{datetime.now(UTC).strftime('%Y%m')}"
    try:
        used = int(await c.get(key) or 0)
        if used >= limit:
            raise QuotaExceeded(
                f"You've used your {limit} monthly AI requests. "
                "The allowance resets at the start of next month."
            )
    except QuotaExceeded:
        raise
    except Exception as exc:
        log.warning("quota_check_failed", error=str(exc))


async def bump_quota(user_id: str) -> None:
    c = get_client()
    if c is None:
        return
    key = f"quota:{user_id}:{datetime.now(UTC).strftime('%Y%m')}"
    try:
        if await c.incr(key) == 1:
            await c.expire(key, 60 * 60 * 24 * 40)
    except Exception as exc:
        log.warning("quota_bump_failed", error=str(exc))


async def quota_state(user_id: str) -> dict[str, int | str | None]:
    c = get_client()
    limit = settings.FREE_MONTHLY_AI_CALLS
    used = 0
    if c is not None:
        try:
            used = int(await c.get(f"quota:{user_id}:{datetime.now(UTC).strftime('%Y%m')}") or 0)
        except Exception:
            pass
    now = datetime.now(UTC)
    resets = datetime(
        now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=UTC
    )
    return {
        "limit_calls": limit,
        "used_calls": used,
        "resets_at": resets.isoformat().replace("+00:00", "Z"),
    }
