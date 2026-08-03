"""Turns a pending `Document` row into ready-to-retrieve `Chunk`s + vectors.

This is the one function the admin API and the background worker both call:
`ingest_document(db, document_id)`. It owns the whole pipeline — parse → chunk →
persist rows → embed → upsert into the vector store → mark `ready` — and it never
lets an exception escape: every failure mode ends with `documents.status = "failed"`
plus a short human `error`, because a row stuck in "processing" forever would hang
the admin's polling UI (API_CONTRACT.md §8) with no way out but a manual DB fix.
"""

from __future__ import annotations

import hashlib
import uuid

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.db.models import Chunk, Document
from app.rag.chunker import chunk_text
from app.rag.embedder import get_embedder
from app.rag.parsers import ParsedDoc, parse
from app.rag.vector_store import get_vector_store

log = structlog.get_logger(__name__)

# Batching embeds keeps one huge document from opening a single enormous
# OpenRouter request, and from holding every chunk's vector in memory at once.
_EMBED_BATCH_SIZE = 64
_WORDS_PER_MINUTE = 200  # rough reading-speed estimate for `reading_minutes`


async def ingest_document(db: AsyncSession, document_id: uuid.UUID | str) -> None:
    """Run the full ingestion pipeline for one `Document` row.

    Safe to call repeatedly for the same id (reingest) — chunks + vectors from a
    prior attempt are purged first — and never raises: any failure is captured
    as `documents.status="failed"` so the row can never get stuck "processing".
    """
    doc_id = document_id if isinstance(document_id, uuid.UUID) else uuid.UUID(str(document_id))
    document = await db.get(Document, doc_id)
    if document is None:
        log.warning("ingest_document_not_found", document_id=str(doc_id))
        return

    document.status = "processing"
    document.error = None
    await db.commit()

    try:
        await _run_pipeline(db, document)
    except Exception as exc:  # noqa: BLE001 - the whole point: never let this escape
        log.exception("ingest_document_failed", document_id=str(doc_id))
        # Any statement issued after the exception's cause (a half-flushed chunk
        # insert, a partial delete) needs to be discarded before the session can
        # be used again, and rollback() expires every attribute on `document` —
        # re-fetching gives us a clean, writable instance for the failure write.
        await db.rollback()
        failed = await db.get(Document, doc_id)
        if failed is not None:
            failed.status = "failed"
            failed.error = _short_error(exc)
            await db.commit()


async def _run_pipeline(db: AsyncSession, document: Document) -> None:
    # Idempotent reingest: wipe whatever a previous attempt produced before doing
    # any new work, so a retried document never accumulates duplicate chunks/
    # vectors alongside the freshly generated ones.
    await db.execute(sa_delete(Chunk).where(Chunk.document_id == document.id))
    await get_vector_store().delete_by_document(document.collection, str(document.id))
    await db.commit()

    if document.storage_path:
        parsed = await parse(document.source_type, path=document.storage_path)
    elif document.source_url:
        parsed = await parse(document.source_type, url=document.source_url)
    else:
        raise ValidationError("Document has neither a storage_path nor a source_url.")

    if document.source_type == "rss":
        await _ingest_rss_feed(db, document, parsed)
        return

    text = (parsed.text or "").strip()
    if not text:
        _mark_failed(document, "No extractable text was found in the source.")
        await db.commit()
        return

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    duplicate = await _find_duplicate(db, content_hash, exclude_id=document.id)
    if duplicate is not None:
        _mark_failed(
            document, f"Duplicate of existing document {duplicate.id} ({duplicate.title})."
        )
        await db.commit()
        return

    drafts = chunk_text(text, pages=parsed.pages)
    if not drafts:
        _mark_failed(document, "The source produced no usable chunks.")
        await db.commit()
        return

    chunks = [
        Chunk(
            document_id=document.id,
            ordinal=d.ordinal,
            text=d.text,
            heading=d.heading,
            page=d.page,
            token_count=d.token_count,
            cefr_level=document.cefr_level,
            skill=document.skill,
        )
        for d in drafts
    ]
    db.add_all(chunks)
    await db.flush()  # assigns each chunk.id — needed for the vector payload below

    await _embed_and_upsert(document, chunks)

    document.title = document.title or parsed.title
    document.content_md = text
    document.content_hash = content_hash
    document.chunk_count = len(chunks)
    document.reading_minutes = max(1, round(len(text.split()) / _WORDS_PER_MINUTE))
    document.status = "ready"
    document.error = None
    await db.commit()


async def _embed_and_upsert(document: Document, chunks: list[Chunk]) -> None:
    embedder = get_embedder()
    store = get_vector_store()
    for start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[start : start + _EMBED_BATCH_SIZE]
        vectors = await embedder.embed_documents([c.text for c in batch])
        payload = [
            {
                "id": str(c.id),
                "vector": vector,
                "document_id": str(document.id),
                "text": c.text,
                "title": document.title,
                "page": c.page,
                "cefr_level": c.cefr_level,
                "skill": c.skill,
            }
            for c, vector in zip(batch, vectors, strict=True)
        ]
        await store.upsert(document.collection, payload)


async def _ingest_rss_feed(db: AsyncSession, document: Document, parsed: ParsedDoc) -> None:
    """An RSS feed carries no text of its own — each entry becomes its own
    `Document`, fanned out and enqueued individually (see `parsers.ParsedDoc`)."""
    from app.workers.ingest import enqueue  # lazy: avoids a top-level import cycle

    children: list[Document] = []
    for item in parsed.items or []:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        child = Document(
            created_by=document.created_by,
            title=item.get("title") or url,
            source_type="web",
            source_url=url,
            # Inherited from the parent: a feed's children teach the same
            # language as the feed, never the 'de' column default.
            language=document.language,
            cefr_level=document.cefr_level,
            skill=document.skill,
            collection=document.collection,
            status="pending",
        )
        db.add(child)
        children.append(child)

    document.title = document.title or parsed.title
    document.chunk_count = 0
    document.reading_minutes = 0
    document.status = "ready"
    document.error = None
    await db.commit()  # also assigns ids to `children`

    for child in children:
        await enqueue(child.id)


async def _find_duplicate(
    db: AsyncSession, content_hash: str, *, exclude_id: uuid.UUID
) -> Document | None:
    stmt = select(Document).where(
        Document.content_hash == content_hash,
        Document.status == "ready",
        Document.id != exclude_id,
    )
    return (await db.execute(stmt)).scalars().first()


def _mark_failed(document: Document, message: str) -> None:
    document.status = "failed"
    document.error = message
    document.chunk_count = 0


def _short_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= 500 else text[:497] + "..."
