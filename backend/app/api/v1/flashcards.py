"""Flashcards — API_CONTRACT.md §5.

Mounted at `/flashcards` (see app/api/v1/__init__.py), so paths here are
relative: `/due`, `/{card_id}/grade`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound
from app.db.models import Flashcard
from app.services.srs import grade_card

log = structlog.get_logger(__name__)

router = APIRouter()


class GradeRequest(BaseModel):
    grade: Literal["again", "hard", "good", "easy"]


class DueCard(BaseModel):
    card_id: str
    vocabulary_id: str
    lemma: str
    meaning: str | None
    # A list field is never null: a card built from a word list has no example
    # sentences, and "absent" should read as an empty list, not as a hole the
    # client has to guard. `ipa` stays nullable — there is no empty IPA.
    examples: list[dict]
    ipa: str | None
    reps: int
    interval_days: int


class DueResponse(BaseModel):
    items: list[DueCard]
    remaining: int


class GradeResponse(BaseModel):
    card_id: str
    interval_days: int
    due_at: str
    reps: int
    status: str


@router.get("/due")
async def list_due(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> DueResponse:
    now = datetime.now(UTC)
    base_filter = (Flashcard.user_id == user.id, Flashcard.due_at <= now)

    total_due = (
        await db.execute(select(func.count()).select_from(Flashcard).where(*base_filter))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Flashcard)
            .options(selectinload(Flashcard.vocabulary))
            .where(*base_filter)
            .order_by(Flashcard.due_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    items = [
        DueCard(
            card_id=str(card.id),
            vocabulary_id=str(card.vocabulary_id),
            lemma=card.vocabulary.lemma if card.vocabulary else "",
            meaning=card.vocabulary.meaning if card.vocabulary else None,
            examples=(card.vocabulary.examples if card.vocabulary else None) or [],
            ipa=card.vocabulary.ipa if card.vocabulary else None,
            reps=card.reps,
            interval_days=card.interval_days,
        )
        for card in rows
    ]
    remaining = max(total_due - len(items), 0)
    return DueResponse(items=items, remaining=remaining)


@router.post("/{card_id}/grade")
async def grade(
    card_id: str, payload: GradeRequest, user: CurrentUser, db: DbSession
) -> GradeResponse:
    try:
        card_uuid = uuid.UUID(card_id)
    except ValueError as exc:
        raise NotFound("Flashcard not found.") from exc

    card = (
        await db.execute(
            select(Flashcard)
            .options(selectinload(Flashcard.vocabulary))
            .where(Flashcard.id == card_uuid, Flashcard.user_id == user.id)
        )
    ).scalar_one_or_none()
    if card is None:
        # Covers both "doesn't exist" and "belongs to someone else" — never
        # distinguish the two to a caller.
        raise NotFound("Flashcard not found.")

    grade_card(card, payload.grade)  # mutates card + card.vocabulary.status in place
    await db.commit()

    log.info("flashcard_graded", card_id=card_id, grade=payload.grade, user_id=str(user.id))
    return GradeResponse(
        card_id=str(card.id),
        interval_days=card.interval_days,
        due_at=card.due_at.isoformat(),
        reps=card.reps,
        status=card.vocabulary.status if card.vocabulary else "learning",
    )
