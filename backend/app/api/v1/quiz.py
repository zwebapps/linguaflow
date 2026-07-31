"""Quiz generation + grading — API_CONTRACT.md §6.

Correct answers are generated and persisted here, but `expected` must never
reach a `/generate` response — grading happens entirely server-side against the
stored `Quiz.questions` JSONB, which is the only place the answer key lives
after this request returns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import structured
from app.core.cache import bump_quota, enforce_monthly_quota, enforce_rate_limit
from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound, ValidationError
from app.db.models import Quiz, TopicStat
from app.rag import retriever as rag_retriever
from app.rag.contracts import SearchResult
from app.services.scoring import estimate_cefr_from_score, grade_quiz

log = structlog.get_logger(__name__)
router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]

# How many knowledge-base passages to ground a generated quiz in. Small on
# purpose — this is context for question-writing, not a full retrieval result set.
_QUIZ_RETRIEVAL_K = 4


# ── Schemas ───────────────────────────────────────────────────────────────────


class QuizGenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    cefr_level: CEFR
    n: int = Field(ge=1, le=20)
    document_id: uuid.UUID | None = None


class QuizQuestionOut(BaseModel):
    id: str
    type: Literal["mcq", "cloze"]
    prompt: str
    options: list[str] | None = None
    hint: str | None = None


class SourceOut(BaseModel):
    document_id: str
    title: str
    snippet: str


class QuizGenerateResponse(BaseModel):
    quiz_id: uuid.UUID
    topic: str
    cefr_level: str
    questions: list[QuizQuestionOut]
    sources: list[SourceOut]


class QuizAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    value: str = Field(default="", max_length=500)


class QuizSubmitRequest(BaseModel):
    quiz_id: uuid.UUID
    answers: list[QuizAnswer]


class QuizResultOut(BaseModel):
    question_id: str
    correct: bool
    expected: str
    given: str | None
    explanation: str


class QuizSubmitResponse(BaseModel):
    quiz_id: uuid.UUID
    score: float
    correct: int
    total: int
    results: list[QuizResultOut]
    cefr_estimate: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _passages_and_sources(
    result: SearchResult,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split one retrieval into (a) LLM grounding context and (b) the citation
    list the client sees — the former carries full text, the latter only a
    snippet, matching how `sources[]` is shaped everywhere else in the contract.
    """
    passages = [{"id": c.id, "title": c.title, "text": c.text} for c in result.results]
    sources = [
        {"document_id": c.document_id, "title": c.title, "snippet": c.snippet}
        for c in result.results
    ]
    return passages, sources


async def _bump_topic_stat(db: DbSession, user_id: uuid.UUID, topic: str, grade: dict) -> None:
    """Roll this submission's per-question tally into the topic's running
    accuracy — the same row `services.scoring.weak_spots` reads later.
    """
    row = (
        await db.execute(
            select(TopicStat).where(TopicStat.user_id == user_id, TopicStat.topic == topic)
        )
    ).scalar_one_or_none()
    if row is None:
        row = TopicStat(user_id=user_id, topic=topic, attempts=0, correct=0)
        db.add(row)
    row.attempts += grade["total"]
    row.correct += grade["correct"]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate(
    payload: QuizGenerateRequest, db: DbSession, user: CurrentUser
) -> QuizGenerateResponse:
    await enforce_rate_limit(str(user.id), bucket="quiz")
    await enforce_monthly_quota(str(user.id))

    result = await rag_retriever.retrieve(
        db,
        payload.topic,
        cefr_level=payload.cefr_level,
        k=_QUIZ_RETRIEVAL_K,
        document_id=str(payload.document_id) if payload.document_id else None,
    )
    passages, sources = _passages_and_sources(result)

    tgt, native = _learner_languages(user)
    generated = await structured.generate_quiz(
        db,
        topic=payload.topic,
        cefr_level=payload.cefr_level,
        n=payload.n,
        user_id=user.id,
        passages=passages or None,
        target_language=tgt,
        native_language=native,
    )

    await bump_quota(str(user.id))

    # The answer key (`expected`) is persisted here and ONLY here — this is the
    # one write of the full GeneratedQuiz, including the field the response
    # below deliberately omits.
    quiz = Quiz(
        user_id=user.id,
        topic=generated.topic,
        cefr_level=generated.cefr_level,
        questions=[q.model_dump() for q in generated.questions],
        sources=sources or None,
    )
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)

    log.info(
        "quiz_generated",
        quiz_id=str(quiz.id),
        topic=quiz.topic,
        n_questions=len(generated.questions),
        user_id=str(user.id),
    )

    return QuizGenerateResponse(
        quiz_id=quiz.id,
        topic=quiz.topic,
        cefr_level=quiz.cefr_level or payload.cefr_level,
        questions=[
            # No `expected` here — this is the redaction boundary. Anything added
            # to QuizQuestionOut later must stay client-safe by construction.
            QuizQuestionOut(id=q.id, type=q.type, prompt=q.prompt, options=q.options, hint=None)
            for q in generated.questions
        ],
        sources=[SourceOut(**s) for s in sources],
    )


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit(
    payload: QuizSubmitRequest, db: DbSession, user: CurrentUser
) -> QuizSubmitResponse:
    quiz = await db.get(Quiz, payload.quiz_id)
    if quiz is None or quiz.user_id != user.id:
        # 404, not 403 — same convention as chat.py's _owned_thread: don't
        # confirm to a caller that a quiz belonging to someone else exists.
        raise NotFound("Quiz not found.")
    if quiz.submitted_at is not None:
        raise ValidationError("This quiz has already been submitted.")

    grade = grade_quiz(quiz.questions, [a.model_dump() for a in payload.answers])

    quiz.submitted_at = datetime.now(UTC)
    quiz.score = grade["score"]
    await _bump_topic_stat(db, user.id, quiz.topic, grade)
    await db.commit()

    log.info(
        "quiz_submitted",
        quiz_id=str(quiz.id),
        score=grade["score"],
        user_id=str(user.id),
    )

    return QuizSubmitResponse(
        quiz_id=quiz.id,
        score=grade["score"],
        correct=grade["correct"],
        total=grade["total"],
        results=[QuizResultOut(**r) for r in grade["results"]],
        cefr_estimate=estimate_cefr_from_score(quiz.cefr_level, grade["score"]),
    )


def _learner_languages(user) -> tuple[str, str]:
    """(target, native) as display names for the prompt.

    Feedback the learner cannot read is feedback that does not exist — an A1
    Turkish learner gets corrections explained in Turkish, not English.
    """
    from app.ai.languages import native_name, target

    return (
        target(getattr(user, "target_language", None)).name,
        native_name(getattr(user, "native_language", None)),
    )
