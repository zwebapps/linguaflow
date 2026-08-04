"""Library & Reading Mode — API_CONTRACT.md §4.

Mounted at `/library` (see app/api/v1/__init__.py), so paths here are relative:
`""`, `"/{id}"`. Only admin-curated documents with `status="ready"` are ever
visible here — a `pending`/`processing`/`failed` row is an admin-side concern,
not something a learner should ever see or link into.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound, ValidationError
from app.db.models import Document

router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]


# ── Schemas ────────────────────────────────────────────────────────────────────


class LibraryItem(BaseModel):
    id: str
    title: str
    source_type: str
    cefr_level: str | None
    skill: str | None
    chunk_count: int
    reading_minutes: int | None
    created_at: Any


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    next_cursor: str | None = None


class LibraryDetail(BaseModel):
    id: str
    title: str
    cefr_level: str | None
    skill: str | None
    source_type: str
    source_url: str | None
    reading_minutes: int | None
    content_md: str | None
    # "prose" | "wordlist". A vocabulary PDF is a TABLE that lost its columns
    # during text extraction; rendering it as paragraphs is unreadable, so the
    # client is told what it is and draws the columns back.
    content_kind: str
    wordlist: list[dict[str, str]] | None
    chunk_count: int
    created_at: Any


# ── View helpers ───────────────────────────────────────────────────────────────


def _list_view(document: Document) -> LibraryItem:
    return LibraryItem(
        id=str(document.id),
        title=document.title,
        source_type=document.source_type,
        cefr_level=document.cefr_level,
        skill=document.skill,
        chunk_count=document.chunk_count,
        reading_minutes=document.reading_minutes,
        created_at=document.created_at,
    )


def _detail_view(document: Document) -> LibraryDetail:
    # Detected per request rather than stored: it's a regex over already-loaded
    # text (~ms for a 500-entry list) and it needs no migration, so a document
    # ingested before this existed renders correctly too.
    from app.services.doc_enrich import looks_like_wordlist, parse_wordlist

    content = document.content_md or ""
    kind = "wordlist" if looks_like_wordlist(content) else "prose"
    rows = parse_wordlist(content) if kind == "wordlist" else []

    return LibraryDetail(
        id=str(document.id),
        title=document.title,
        cefr_level=document.cefr_level,
        skill=document.skill,
        source_type=document.source_type,
        source_url=document.source_url,
        reading_minutes=document.reading_minutes,
        content_md=document.content_md,
        content_kind=kind,
        wordlist=rows or None,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_library(
    user: CurrentUser,
    db: DbSession,
    level: Annotated[CEFR | None, Query()] = None,
    skill: Annotated[str | None, Query(max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    # Defaults to what the learner is studying. Explicit so a learner studying
    # two languages can browse the other one without switching their profile.
    language: Annotated[str | None, Query(max_length=5)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> LibraryPage:
    # Language is applied ALWAYS, never optionally. Content is implicitly
    # single-language everywhere else in the product, so an unfiltered library
    # would quietly serve German readers to a Spanish learner — a wrong answer
    # that looks like a working feature.
    stmt = select(Document).where(
        Document.status == "ready",
        Document.language == (language or user.target_language),
    )
    if level is not None:
        stmt = stmt.where(Document.cefr_level == level)
    if skill is not None:
        stmt = stmt.where(Document.skill == skill)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))

    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError as exc:
            raise ValidationError("Invalid cursor.") from exc
        stmt = stmt.where(Document.created_at < cursor_dt)

    stmt = stmt.order_by(Document.created_at.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return LibraryPage(
        items=[_list_view(d) for d in rows],
        next_cursor=rows[-1].created_at.isoformat() if (has_more and rows) else None,
    )


@router.get("/{document_id}")
async def get_library_document(
    document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> LibraryDetail:
    document = (
        await db.execute(
            # Language-checked on the detail route too: a document id is
            # guessable, and "not in your language" should read as not found
            # rather than handing over another course's material.
            select(Document).where(
                Document.id == document_id,
                Document.status == "ready",
                Document.language == user.target_language,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        # Same 404 whether the id never existed, still isn't ready, or failed —
        # a learner has no legitimate use for any of those distinctions.
        raise NotFound("That document isn't in the library.")
    return _detail_view(document)
