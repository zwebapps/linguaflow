"""Background ingestion worker.

`enqueue()` is what `app/api/v1/admin.py` calls right after creating a `Document`
row — it pushes a job onto a Redis list so the request can return `202` without
waiting for parse/chunk/embed to finish. `main()` is a standalone consumer loop
(`python -m app.workers.ingest`) that BLPOPs jobs and runs the real pipeline, one
DB session per job.

If Redis isn't reachable, `enqueue()` falls back to firing the ingestion as a
plain asyncio task so local dev works end-to-end with zero worker process
running — the same "degrade, don't 500" posture as `app.core.cache`.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from app.core.cache import get_client
from app.core.config import settings
from app.db.session import SessionLocal
from app.rag.ingest import ingest_document

log = structlog.get_logger(__name__)

_QUEUE_KEY = "queue:ingest"

# Keeps the inline-fallback tasks referenced so they can't be garbage-collected
# mid-flight — `asyncio.create_task` result must be held by *someone*.
_inline_tasks: set[asyncio.Task] = set()


async def enqueue(document_id: uuid.UUID | str) -> None:
    doc_id = str(document_id)
    client = get_client()
    if client is not None:
        try:
            await client.rpush(_QUEUE_KEY, doc_id)
            return
        except Exception as exc:
            log.warning("ingest_enqueue_redis_failed", document_id=doc_id, error=str(exc))

    log.info("ingest_enqueue_fallback_inline", document_id=doc_id)
    task = asyncio.create_task(_run_inline(doc_id))
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


async def _run_inline(doc_id: str) -> None:
    async with SessionLocal() as db:
        try:
            await ingest_document(db, doc_id)
        except Exception:
            # ingest_document already converts real failures into a `failed` row
            # status — this is only a last-resort net around that call itself.
            log.exception("ingest_inline_task_failed", document_id=doc_id)


async def _process_one(doc_id: str) -> None:
    log.info("ingest_job_started", document_id=doc_id)
    async with SessionLocal() as db:
        try:
            await ingest_document(db, doc_id)
            log.info("ingest_job_finished", document_id=doc_id)
        except Exception:
            log.exception("ingest_job_crashed", document_id=doc_id)


async def _consume_forever() -> None:
    client = get_client()
    if client is None:
        raise RuntimeError("Redis is required to run the ingest worker (check REDIS_URL).")

    log.info(
        "ingest_worker_started", queue=_QUEUE_KEY, block_seconds=settings.INGEST_BLOCK_SECONDS
    )
    failures = 0
    while True:
        try:
            # A finite timeout (rather than blocking forever) means a dead/
            # restarted Redis is noticed and retried instead of hanging BLPOP.
            # The length is tuned for billed-per-command managed Redis — see
            # INGEST_BLOCK_SECONDS.
            item = await client.blpop([_QUEUE_KEY], timeout=settings.INGEST_BLOCK_SECONDS)
            failures = 0
        except Exception as exc:
            # A dropped idle connection is routine on managed Redis and the next
            # poll reconnects, so don't cry wolf on the first one; escalate only
            # when failures persist (i.e. the queue really is unreachable).
            failures += 1
            log_at = log.warning if failures >= 3 else log.info
            log_at("ingest_worker_blpop_failed", error=str(exc), consecutive=failures)
            # Back off gently rather than hammering a struggling broker.
            await asyncio.sleep(min(30, 2 ** min(failures, 5)))
            continue
        if item is None:
            continue  # timed out with no job — loop again
        _key, doc_id = item
        # `decode_responses=True` on the client makes this `str` at runtime; the
        # redis-py stubs still type it as `bytes | str`, so make that explicit.
        await _process_one(str(doc_id))


def main() -> None:
    asyncio.run(_consume_forever())


if __name__ == "__main__":
    main()
