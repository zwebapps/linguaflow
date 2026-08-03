"""Vocabulary — API_CONTRACT.md §5.

Mounted at `/vocab` (see app/api/v1/__init__.py), so paths here are relative:
`""`, `"/{id}"`.
"""

from __future__ import annotations

import base64
import inspect
import re
import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound, ValidationError
from app.db.models import Flashcard, Vocabulary

log = structlog.get_logger(__name__)

router = APIRouter()

VocabStatus = Literal["new", "learning", "mastered"]

# §11: lemma is 1-64 chars, letters/äöüß/- only (plus a space, since "der Tisch"
# style enriched lemmas are legitimate stored values, not just raw input).
_LEMMA_RE = re.compile(r"^[A-Za-zÄÖÜäöüß\- ]{1,64}$")


# ── Request/response models ───────────────────────────────────────────────────


class CreateVocabRequest(BaseModel):
    lemma: str = Field(min_length=1, max_length=64)
    source_document_id: str | None = None

    @field_validator("lemma")
    @classmethod
    def _lemma_charset(cls, v: str) -> str:
        v = v.strip()
        if not _LEMMA_RE.match(v):
            raise ValueError("lemma must be 1-64 chars, letters/äöüß/- only")
        return v


class VocabOut(BaseModel):
    id: str
    lemma: str
    article: str | None
    plural: str | None
    meaning: str | None
    ipa: str | None
    examples: list[dict] | None
    status: str
    due_at: str | None
    created_at: str


class VocabListResponse(BaseModel):
    items: list[VocabOut]
    next_cursor: str | None


def _vocab_view(vocab: Vocabulary) -> VocabOut:
    due_at = vocab.card.due_at if vocab.card else None
    return VocabOut(
        id=str(vocab.id),
        lemma=vocab.lemma,
        article=vocab.article,
        plural=vocab.plural,
        meaning=vocab.meaning,
        ipa=vocab.ipa,
        examples=vocab.examples,
        status=vocab.status,
        due_at=due_at.isoformat() if due_at else None,
        created_at=vocab.created_at.isoformat(),
    )


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, row_id = raw.split("|", 1)
        return datetime.fromisoformat(created_at_str), row_id
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad cursor
        raise ValidationError("Invalid pagination cursor.") from exc


async def _find_by_lemma(
    db: DbSession, user_id: Any, lemma: str, language: str
) -> Vocabulary | None:
    """Existing entry for this lemma IN THIS LANGUAGE.

    Language is part of the identity of a word, not a detail of it. Without it,
    saving Spanish "sin" would collide with German "sin"-spelled entries and one
    learner's decks would bleed into each other.
    """
    stmt = (
        select(Vocabulary)
        .options(selectinload(Vocabulary.card))
        .where(
            Vocabulary.user_id == user_id,
            Vocabulary.language == language,
            func.lower(Vocabulary.lemma) == lemma.lower(),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lookup_dictionary(lemma: str) -> dict[str, Any] | None:
    """Enrich `lemma` via the dictionary tool if it's landed yet.

    Another agent owns app/ai/tools/dictionary.py in parallel — until it
    exists (or if it errors) we degrade to storing just the bare lemma, per
    the task brief. Guards both the import and the call so a flaky/missing
    dependency never breaks vocab capture.
    """
    try:
        from app.ai.tools.dictionary import lookup  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        result = lookup(lemma)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
        log.warning("vocab_dictionary_lookup_failed", lemma=lemma, error=str(exc))
        return None

    return result if isinstance(result, dict) else None


def _primary_meaning(meanings: list[dict] | None) -> str | None:
    if not meanings:
        return None
    for m in meanings:
        if isinstance(m, dict) and m.get("lang") == "en":
            return m.get("text")
    first = meanings[0]
    return first.get("text") if isinstance(first, dict) else None


def _display_lemma(raw: str, article: str | None) -> str:
    return f"{article} {raw}" if article else raw


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_vocab(
    user: CurrentUser,
    db: DbSession,
    status_filter: VocabStatus | None = Query(default=None, alias="status"),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> VocabListResponse:
    # Scoped to the language being studied: a learner doing German AND Spanish
    # holds "der Tisch" and "la mesa" at once, and each deck must review alone.
    stmt = (
        select(Vocabulary)
        .options(selectinload(Vocabulary.card))
        .where(Vocabulary.user_id == user.id, Vocabulary.language == user.target_language)
    )
    if status_filter is not None:
        stmt = stmt.where(Vocabulary.status == status_filter)

    if cursor is not None:
        after_created_at, after_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Vocabulary.created_at > after_created_at)
            | (
                (Vocabulary.created_at == after_created_at)
                & (Vocabulary.id > uuid.UUID(after_id))
            )
        )

    stmt = stmt.order_by(Vocabulary.created_at.asc(), Vocabulary.id.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id) if len(rows) == limit else None
    return VocabListResponse(items=[_vocab_view(v) for v in rows], next_cursor=next_cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_vocab(payload: CreateVocabRequest, user: CurrentUser, db: DbSession) -> VocabOut:
    existing = await _find_by_lemma(db, user.id, payload.lemma, user.target_language)
    if existing is not None:
        return _vocab_view(existing)

    enriched = await _lookup_dictionary(payload.lemma)
    article = enriched.get("article") if enriched else None

    source_document_id: uuid.UUID | None = None
    if payload.source_document_id:
        try:
            source_document_id = uuid.UUID(payload.source_document_id)
        except ValueError as exc:
            raise ValidationError(
                "source_document_id must be a UUID.",
                details=[{"field": "source_document_id", "issue": "invalid UUID"}],
            ) from exc

    vocab = Vocabulary(
        user_id=user.id,
        # Stamped from the learner's current target so a word saved while
        # studying Spanish never surfaces in a German review session.
        language=user.target_language,
        lemma=_display_lemma(payload.lemma, article) if enriched else payload.lemma,
        article=article,
        plural=enriched.get("plural") if enriched else None,
        pos=enriched.get("pos") if enriched else None,
        meaning=_primary_meaning(enriched.get("meanings")) if enriched else None,
        ipa=enriched.get("ipa") if enriched else None,
        examples=enriched.get("examples") if enriched else None,
        meanings=enriched.get("meanings") if enriched else None,
        source_document_id=source_document_id,
    )
    db.add(vocab)
    try:
        await db.flush()
    except IntegrityError:
        # Idempotency race: another request created the same (user, lemma) row
        # between our pre-check and this insert. Roll back and return that row.
        await db.rollback()
        existing = await _find_by_lemma(
            db, user.id, payload.lemma, user.target_language
        ) or await _find_by_lemma(db, user.id, vocab.lemma, user.target_language)
        if existing is not None:
            return _vocab_view(existing)
        raise

    card = Flashcard(user_id=user.id, vocabulary_id=vocab.id)
    db.add(card)
    await db.commit()

    vocab.card = card
    log.info(
        "vocab_created", vocab_id=str(vocab.id), lemma=vocab.lemma, enriched=enriched is not None
    )
    return _vocab_view(vocab)


@router.delete("/{vocab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vocab(vocab_id: str, user: CurrentUser, db: DbSession) -> None:
    try:
        vocab_uuid = uuid.UUID(vocab_id)
    except ValueError as exc:
        raise NotFound("Vocabulary entry not found.") from exc

    vocab = (
        await db.execute(
            select(Vocabulary).where(Vocabulary.id == vocab_uuid, Vocabulary.user_id == user.id)
        )
    ).scalar_one_or_none()
    if vocab is None:
        # Same 404 whether it never existed or belongs to another user — a
        # user must never learn a given id exists in someone else's account.
        raise NotFound("Vocabulary entry not found.")

    await db.delete(vocab)  # cascades to the linked Flashcard (relationship + FK)
    await db.commit()
