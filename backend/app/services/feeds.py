"""Scheduled RSS refresh — automated knowledge-base updates.

The admin registers a feed once; this polls it on an interval and ingests only
what's new, so the reading library keeps growing without anyone touching it.

Two things make this safe to run unattended:

* **Due-only polling.** A feed is polled when `last_polled_at` is older than its
  `poll_interval_minutes`, so restarting the worker doesn't re-fetch everything and
  a tight loop can't hammer a publisher.
* **Per-feed isolation.** One broken feed (dead host, malformed XML, a URL that now
  resolves to a private address) must not stop the others, so every feed is polled
  in its own try/except and its failure is recorded on the row.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, FeedSource
from app.rag.parsers import validate_public_url

log = structlog.get_logger(__name__)

# How long a single poll cycle may take before we move on. A slow publisher
# shouldn't wedge the scheduler.
_POLL_TIMEOUT_S = 90

# Politeness floor. Even if an admin sets 1 minute, we won't poll a publisher more
# often than this.
_MIN_INTERVAL_MINUTES = 15


def _is_due(feed: FeedSource, now: datetime) -> bool:
    if not feed.is_active:
        return False
    if feed.last_polled_at is None:
        return True
    interval = max(_MIN_INTERVAL_MINUTES, int(feed.poll_interval_minutes or 1440))
    return feed.last_polled_at + timedelta(minutes=interval) <= now


async def due_feeds(db: AsyncSession, now: datetime | None = None) -> list[FeedSource]:
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(select(FeedSource).where(FeedSource.is_active.is_(True)))
    ).scalars().all()
    return [f for f in rows if _is_due(f, now)]


async def poll_feed(db: AsyncSession, feed: FeedSource) -> dict[str, Any]:
    """Fetch one feed and ingest new items. Returns a small result summary.

    Reuses the existing document-ingestion path rather than a second pipeline: a
    feed item is just a `web` document, so it gets the same parsing, chunking,
    embedding and dedup as an admin-submitted link.
    """
    from app.rag.ingest import ingest_document
    from app.rag.parsers import parse

    result: dict[str, Any] = {"feed_id": str(feed.id), "url": feed.url, "new_items": 0}

    # Re-validate on every poll, not just at registration: DNS can change under a
    # URL that was public when an admin added it.
    validate_public_url(feed.url)

    parsed = await parse("rss", url=feed.url)
    items = list(parsed.items or [])
    if not items:
        result["note"] = "feed returned no items"
        feed.last_polled_at = datetime.now(UTC)
        await db.commit()
        return result

    # `last_seen_guid` is the high-water mark. Items above it are new; once we hit
    # it we stop, because feeds are newest-first.
    seen = feed.last_seen_guid
    fresh: list[dict[str, Any]] = []
    for item in items:
        guid = str(item.get("url") or item.get("id") or item.get("title") or "")
        if seen and guid == seen:
            break
        if guid:
            fresh.append({**item, "_guid": guid})

    ingested = 0
    for item in fresh:
        url = item.get("url")
        if not url:
            continue
        try:
            validate_public_url(str(url))
        except Exception as exc:
            log.warning("feed_item_url_rejected", url=str(url)[:120], error=str(exc)[:120])
            continue

        # Skip anything already in the library — cheap guard before we spend an
        # embedding call on it.
        existing = (
            await db.execute(select(Document.id).where(Document.source_url == str(url)))
        ).first()
        if existing:
            continue

        doc = Document(
            created_by=feed.created_by,
            title=str(item.get("title") or url)[:500],
            source_type="web",
            source_url=str(url),
            cefr_level=feed.cefr_level,
            skill=feed.skill,
            status="pending",
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        try:
            await ingest_document(db, doc.id)
            ingested += 1
        except Exception as exc:
            # ingest_document already marks the row failed; just note it and continue.
            log.warning("feed_item_ingest_failed", url=str(url)[:120], error=str(exc)[:160])

    if fresh:
        feed.last_seen_guid = fresh[0]["_guid"]
    feed.items_ingested = int(feed.items_ingested or 0) + ingested
    feed.last_polled_at = datetime.now(UTC)
    await db.commit()

    result["new_items"] = ingested
    log.info("feed_polled", url=feed.url, new_items=ingested, candidates=len(fresh))
    return result


async def poll_due_feeds(db: AsyncSession) -> list[dict[str, Any]]:
    """Poll every feed that is due. One feed's failure never stops the rest."""
    feeds = await due_feeds(db)
    if not feeds:
        return []

    out: list[dict[str, Any]] = []
    for feed in feeds:
        try:
            out.append(
                await asyncio.wait_for(poll_feed(db, feed), timeout=_POLL_TIMEOUT_S)
            )
        except TimeoutError:
            log.warning("feed_poll_timeout", url=feed.url)
            feed.last_polled_at = datetime.now(UTC)  # back off rather than retry-loop
            await db.commit()
            out.append({"feed_id": str(feed.id), "url": feed.url, "error": "timeout"})
        except Exception as exc:
            log.warning("feed_poll_failed", url=feed.url, error=str(exc)[:200])
            feed.last_polled_at = datetime.now(UTC)
            await db.commit()
            out.append({"feed_id": str(feed.id), "url": feed.url, "error": str(exc)[:200]})
    return out
