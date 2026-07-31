"""The scheduler loop — this is what makes knowledge-base updates *automated*.

Run alongside the API:

    python -m app.workers.scheduler

Deliberately a plain asyncio loop rather than APScheduler/Celery: there is exactly
one periodic job, and a dependency-free loop is easier to reason about and to run
as a second Render worker process.

**Single-runner locking.** Two replicas polling the same feed would double-ingest,
so the tick takes a short-lived Redis lock. If Redis is unavailable the lock is
skipped — acceptable for a single-instance local/dev setup, and logged so it is
not a silent assumption.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from app.core.logging import setup_logging

log = structlog.get_logger(__name__)

# How often to *check* for due feeds. Each feed's own poll_interval_minutes decides
# whether it actually gets fetched, so checking often is cheap.
TICK_SECONDS = 300

_LOCK_KEY = "scheduler:feed_tick"
_LOCK_TTL = 600  # > one tick, so a crashed holder can't wedge the loop forever


async def _acquire_lock() -> bool:
    """True if this process may run the tick."""
    from app.core.cache import get_client

    client = get_client()
    if client is None:
        log.warning("scheduler_lock_unavailable", detail="redis down; running unlocked")
        return True
    try:
        # SET NX EX — the standard single-runner primitive.
        return bool(await client.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL))
    except Exception as exc:
        log.warning("scheduler_lock_failed", error=str(exc)[:160])
        return True


async def _release_lock() -> None:
    from app.core.cache import get_client

    client = get_client()
    if client is None:
        return
    with contextlib.suppress(Exception):
        await client.delete(_LOCK_KEY)


async def tick() -> list[dict]:
    """One scheduler pass. Never raises — the loop must survive a bad cycle."""
    from app.db.session import SessionLocal
    from app.services.feeds import poll_due_feeds

    if not await _acquire_lock():
        log.debug("scheduler_tick_skipped", reason="another runner holds the lock")
        return []

    try:
        async with SessionLocal() as db:
            results = await poll_due_feeds(db)
        if results:
            total = sum(int(r.get("new_items") or 0) for r in results)
            log.info("scheduler_tick", feeds=len(results), new_documents=total)
        return results
    except Exception as exc:
        log.error("scheduler_tick_failed", error=str(exc)[:300])
        return []
    finally:
        await _release_lock()


async def run(stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    log.info("scheduler_started", tick_seconds=TICK_SECONDS)
    while not stop.is_set():
        await tick()
        # wait_for on the stop event = responsive shutdown without a sleep(1) poll.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
    log.info("scheduler_stopped")


def main() -> None:  # pragma: no cover - process entrypoint
    setup_logging()
    stop = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        loop.run_until_complete(run(stop))
    finally:
        loop.close()


if __name__ == "__main__":  # pragma: no cover
    main()
