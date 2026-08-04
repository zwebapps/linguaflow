"""Word lists — the vocabulary shelf, separate from the reading library.

A vocabulary PDF is a reference table, not something you read start to finish,
so it gets its own section: browse the entries, search them, and test yourself.

The self-test is built **deterministically from the list itself** — no model
call. Distractors are other entries from the same list, which makes them
plausible by construction (all real words, same topic, same register) and
means practice is instant, free, and works even with no API key. Answers are
checked server-side against the stored list, the same posture as `/quiz`.
"""

from __future__ import annotations

import random
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound, ValidationError
from app.db.models import Document
from app.services.doc_enrich import parse_wordlist

log = structlog.get_logger(__name__)
router = APIRouter()

# A test long enough to be worth taking, short enough to finish in a sitting.
MIN_QUESTIONS, MAX_QUESTIONS, DEFAULT_QUESTIONS = 5, 30, 10
# 4 options = 1 answer + 3 distractors, so a list must have at least 4 entries
# with distinct meanings before it can be tested at all.
OPTIONS_PER_QUESTION = 4


class WordlistSummary(BaseModel):
    id: str
    title: str
    cefr_level: str | None
    language: str
    entries: int
    created_at: Any


class WordlistEntry(BaseModel):
    index: str
    term: str
    gloss: str
    urdu: str
    hindi: str
    roman: str


class WordlistDetail(BaseModel):
    id: str
    title: str
    cefr_level: str | None
    language: str
    source_url: str | None
    total: int
    entries: list[WordlistEntry]


class TestQuestion(BaseModel):
    id: str
    term: str
    options: list[str]


class TestResponse(BaseModel):
    document_id: str
    title: str
    questions: list[TestQuestion]


class TestAnswer(BaseModel):
    question_id: str
    value: str


class SubmitRequest(BaseModel):
    document_id: uuid.UUID
    answers: list[TestAnswer] = Field(default_factory=list)


class SubmitResult(BaseModel):
    question_id: str
    term: str
    correct: bool
    expected: str
    given: str


class SubmitResponse(BaseModel):
    score: float
    correct: int
    total: int
    results: list[SubmitResult]


async def _load(db: DbSession, document_id: uuid.UUID, user: Any) -> tuple[Document, list[dict]]:
    document = await db.get(Document, document_id)
    if document is None or document.status != "ready":
        raise NotFound("That word list doesn't exist.")
    if document.language != user.target_language:
        raise NotFound("That word list isn't in the language you're learning.")
    rows = parse_wordlist(document.content_md or "")
    if not rows:
        raise NotFound("That document has no vocabulary entries.")
    return document, rows


@router.get("")
async def list_wordlists(db: DbSession, user: CurrentUser) -> list[WordlistSummary]:
    """Every vocabulary list in the learner's target language."""
    docs = (
        (
            await db.execute(
                select(Document)
                .where(
                    Document.content_kind == "wordlist",
                    Document.status == "ready",
                    Document.language == user.target_language,
                )
                .order_by(Document.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for d in docs:
        rows = parse_wordlist(d.content_md or "")
        if rows:
            out.append(
                WordlistSummary(
                    id=str(d.id),
                    title=d.title,
                    cefr_level=d.cefr_level,
                    language=d.language,
                    entries=len(rows),
                    created_at=d.created_at,
                )
            )
    return out


@router.get("/{document_id}")
async def get_wordlist(
    document_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> WordlistDetail:
    document, rows = await _load(db, document_id, user)
    if q:
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in r["term"].lower()
            or needle in r["gloss"].lower()
            or needle in r["roman"].lower()
        ]
    return WordlistDetail(
        id=str(document.id),
        title=document.title,
        cefr_level=document.cefr_level,
        language=document.language,
        source_url=document.source_url,
        total=len(rows),
        entries=[WordlistEntry(**r) for r in rows[:limit]],
    )


def build_test(rows: list[dict[str, str]], n: int, rng: random.Random) -> list[dict[str, Any]]:
    """N multiple-choice questions from `rows`. Pure, so it is unit-testable.

    Only entries WITH a meaning can be asked, and the answer must be unique
    among its options — otherwise a learner can be marked wrong for picking an
    identical gloss that happens to belong to a different row.
    """
    # Dedupe by term: the term IS the question id (the client echoes it back
    # for grading), so two rows sharing a headword would collide.
    seen: set[str] = set()
    usable = []
    for r in rows:
        term, gloss = r.get("term"), r.get("gloss")
        if term and gloss and term not in seen:
            seen.add(term)
            usable.append(r)
    # Distinct glosses are what limits the option pool, not row count.
    glosses = sorted({r["gloss"] for r in usable})
    if len(usable) < OPTIONS_PER_QUESTION or len(glosses) < OPTIONS_PER_QUESTION:
        raise ValidationError(
            "This list is too short to build a test — it needs at least "
            f"{OPTIONS_PER_QUESTION} entries with distinct meanings."
        )

    picked = rng.sample(usable, min(n, len(usable)))
    questions: list[dict[str, Any]] = []
    for row in picked:
        pool = [g for g in glosses if g != row["gloss"]]
        options = rng.sample(pool, OPTIONS_PER_QUESTION - 1) + [row["gloss"]]
        rng.shuffle(options)
        questions.append(
            {
                # The term is the id: the client echoes it on submit and the
                # server looks the answer up, so no key ever leaves the server.
                "id": row["term"],
                "term": row["term"],
                "expected": row["gloss"],
                "options": options,
            }
        )
    return questions


@router.get("/{document_id}/test")
async def start_test(
    document_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    n: Annotated[int, Query(ge=MIN_QUESTIONS, le=MAX_QUESTIONS)] = DEFAULT_QUESTIONS,
) -> TestResponse:
    """A fresh self-test. The answer key is NOT sent — grading is server-side."""
    document, rows = await _load(db, document_id, user)
    questions = build_test(rows, n, random.Random())
    return TestResponse(
        document_id=str(document.id),
        title=document.title,
        questions=[
            TestQuestion(id=q["id"], term=q["term"], options=q["options"]) for q in questions
        ],
    )


@router.post("/submit")
async def submit_test(
    payload: SubmitRequest, db: DbSession, user: CurrentUser
) -> SubmitResponse:
    """Grade against the stored list.

    The client sends back the TERM it was asked about, not an answer key, so a
    tampered payload can only change which words it is graded on — never what
    counts as correct.
    """
    _document, rows = await _load(db, payload.document_id, user)
    by_term: dict[str, str] = {r["term"]: r["gloss"] for r in rows if r.get("term")}

    results: list[SubmitResult] = []
    for answer in payload.answers:
        # question_id carries the term (the client echoes what it was asked).
        term = answer.question_id
        expected = by_term.get(term)
        if expected is None:
            continue  # not from this list — ignore rather than fail the submit
        given = (answer.value or "").strip()
        results.append(
            SubmitResult(
                question_id=term,
                term=term,
                correct=given.casefold() == expected.casefold(),
                expected=expected,
                given=given,
            )
        )

    correct = sum(1 for r in results if r.correct)
    total = len(results)
    return SubmitResponse(
        score=round(correct / total, 4) if total else 0.0,
        correct=correct,
        total=total,
        results=results,
    )
