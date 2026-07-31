"""Writing evaluation — API_CONTRACT.md §6 `POST /writing/evaluate`."""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import structured
from app.ai.tasks import TaskType
from app.core.cache import bump_quota, enforce_monthly_quota, enforce_rate_limit
from app.core.deps import CurrentUser, DbSession
from app.db.models import AIUsage, WritingSubmission

log = structlog.get_logger(__name__)
router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]


# ── Schemas ───────────────────────────────────────────────────────────────────


class WritingEvaluateRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=1000)
    text: str = Field(min_length=1, max_length=5000)
    target_level: CEFR


class ScoresOut(BaseModel):
    grammar: float
    vocabulary: float
    coherence: float
    overall: float


class CorrectionOut(BaseModel):
    original: str
    suggestion: str
    explanation: str
    severity: Literal["error", "warning", "style"]
    offset: int
    length: int


class UsageOut(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float


class WritingEvaluateResponse(BaseModel):
    submission_id: uuid.UUID
    scores: ScoresOut
    cefr_estimate: str
    corrections: list[CorrectionOut]
    improved_version: str
    suggestions: list[str]
    usage: UsageOut


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _latest_usage(db: DbSession, user_id: uuid.UUID) -> UsageOut:
    """Best-effort usage snapshot for the call `structured.evaluate_writing` just made.

    That function returns a validated `WritingEvaluation`, not the raw `AIResult`
    — the token/cost numbers live in `AIUsage` instead, written as a side effect
    of `ai_router.complete()` inside it. Reading the most recent row for this
    user+task is how §6's `usage` field gets populated without reaching into the
    structured-output layer's internals. Falls back to zeros (never raises) if
    no row is found, e.g. when a cached/mocked evaluation skipped the router.
    """
    row = (
        await db.execute(
            select(AIUsage)
            .where(
                AIUsage.user_id == user_id,
                AIUsage.task_type == str(TaskType.WRITING_EVALUATE),
            )
            .order_by(AIUsage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return UsageOut(tokens_in=0, tokens_out=0, cost_usd=0.0)
    return UsageOut(
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=round(row.cost_micro_usd / 1_000_000, 6),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/evaluate", response_model=WritingEvaluateResponse)
async def evaluate(
    payload: WritingEvaluateRequest, db: DbSession, user: CurrentUser
) -> WritingEvaluateResponse:
    # A full LLM pass over up to 5000 chars — rate-limit and quota it like the
    # other expensive AI-backed routes (quiz generation, chat).
    await enforce_rate_limit(str(user.id), bucket="writing")
    await enforce_monthly_quota(str(user.id))

    evaluation = await structured.evaluate_writing(
        db,
        text=payload.text,
        target_level=payload.target_level,
        prompt=payload.prompt,
        user_id=user.id,
    )

    await bump_quota(str(user.id))

    submission = WritingSubmission(
        user_id=user.id,
        prompt=payload.prompt,
        text=payload.text,
        target_level=payload.target_level,
        scores=evaluation.scores.model_dump(),
        cefr_estimate=evaluation.cefr_estimate,
        corrections=[c.model_dump() for c in evaluation.corrections],
        improved_version=evaluation.improved_version,
        suggestions=evaluation.suggestions,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    usage = await _latest_usage(db, user.id)

    log.info(
        "writing_evaluated",
        submission_id=str(submission.id),
        target_level=payload.target_level,
        cefr_estimate=evaluation.cefr_estimate,
        user_id=str(user.id),
    )

    return WritingEvaluateResponse(
        submission_id=submission.id,
        scores=ScoresOut(**evaluation.scores.model_dump()),
        cefr_estimate=evaluation.cefr_estimate,
        corrections=[CorrectionOut(**c.model_dump()) for c in evaluation.corrections],
        improved_version=evaluation.improved_version,
        suggestions=evaluation.suggestions,
        usage=usage,
    )
