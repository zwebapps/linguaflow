"""Student-facing analysis dashboard — API_CONTRACT.md §7 `GET /analysis`.

One read-heavy endpoint that assembles the whole payload from several tables;
every number is either a direct aggregate or delegates to a pure function in
`app.services.scoring` so the interesting logic (grading rules, the weak-spot
threshold, the streak rule) stays unit-testable without this endpoint's DB
plumbing in the way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.cache import quota_state
from app.core.deps import CurrentUser, DbSession
from app.db.models import (
    Activity,
    AIUsage,
    Quiz,
    SpeakingSession,
    TopicStat,
    Vocabulary,
    WritingSubmission,
)
from app.services.scoring import (
    derive_skill_scores,
    estimate_cefr_from_score,
    streak_days,
    weak_spots,
)

log = structlog.get_logger(__name__)
router = APIRouter()

# §7's `activity[]` is a rolling window for the chart, not the full history —
# the streak calculation below still walks the *entire* Activity table.
_ACTIVITY_WINDOW_DAYS = 30


# ── Schemas ───────────────────────────────────────────────────────────────────


class SkillsOut(BaseModel):
    reading: float | None
    listening: float | None
    speaking: float | None
    writing: float | None
    grammar: float | None
    vocabulary: float | None


class CountersOut(BaseModel):
    vocab_total: int
    vocab_mastered: int
    quizzes_taken: int
    writings_submitted: int
    streak_days: int


class ActivityDayOut(BaseModel):
    day: str
    minutes: int
    xp: int


class WeakSpotOut(BaseModel):
    topic: str
    accuracy: float
    attempts: int
    recommendation: str
    document_id: str | None


class CefrTrendPointOut(BaseModel):
    day: str
    estimate: str


class ByModelOut(BaseModel):
    model: str
    cost_usd: float
    calls: int


class QuotaOut(BaseModel):
    limit_calls: int | None
    used_calls: int | None
    resets_at: str | None


class UsageOut(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    by_model: list[ByModelOut]
    quota: QuotaOut


class SpeakingSessionOut(BaseModel):
    """A finished spoken session — the one skill that had no history before."""

    id: str
    scenario: str
    cefr_level: str
    turns: int
    overall: float
    grammar: float
    fluency: float
    feedback: str | None
    created_at: str


class AnalysisResponse(BaseModel):
    cefr_level: str
    skills: SkillsOut
    counters: CountersOut
    activity: list[ActivityDayOut]
    weak_spots: list[WeakSpotOut]
    cefr_trend: list[CefrTrendPointOut]
    speaking_sessions: list[SpeakingSessionOut]
    usage: UsageOut


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("", response_model=AnalysisResponse)
async def get_analysis(db: DbSession, user: CurrentUser) -> AnalysisResponse:
    vocab_total = (
        await db.execute(
            select(func.count()).select_from(Vocabulary).where(Vocabulary.user_id == user.id)
        )
    ).scalar_one()
    vocab_mastered = (
        await db.execute(
            select(func.count())
            .select_from(Vocabulary)
            .where(Vocabulary.user_id == user.id, Vocabulary.status == "mastered")
        )
    ).scalar_one()

    submitted_quizzes = (
        (
            await db.execute(
                select(Quiz).where(Quiz.user_id == user.id, Quiz.submitted_at.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    quizzes_taken = len(submitted_quizzes)
    quiz_accuracy = (
        round(sum(q.score or 0.0 for q in submitted_quizzes) / quizzes_taken, 4)
        if quizzes_taken
        else None
    )

    writings = (
        (await db.execute(select(WritingSubmission).where(WritingSubmission.user_id == user.id)))
        .scalars()
        .all()
    )
    writings_submitted = len(writings)
    writing_overall_avg = (
        round(sum((w.scores or {}).get("overall", 0.0) for w in writings) / writings_submitted, 4)
        if writings_submitted
        else None
    )

    skills = derive_skill_scores(
        quiz_accuracy=quiz_accuracy,
        writing_overall_avg=writing_overall_avg,
        vocab_mastered=vocab_mastered,
        vocab_total=vocab_total,
    )

    activity_rows = (
        (
            await db.execute(
                select(Activity).where(Activity.user_id == user.id).order_by(Activity.day.asc())
            )
        )
        .scalars()
        .all()
    )
    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=_ACTIVITY_WINDOW_DAYS - 1)
    activity = [
        ActivityDayOut(day=r.day.isoformat(), minutes=r.minutes, xp=r.xp)
        for r in activity_rows
        if r.day >= window_start
    ]
    # Streak uses the full history, not just the 30-day chart window — a streak
    # longer than the window shouldn't be truncated to it.
    streak = streak_days((r.day for r in activity_rows), today=today)

    topic_rows = (
        (await db.execute(select(TopicStat).where(TopicStat.user_id == user.id))).scalars().all()
    )
    weak = weak_spots(topic_rows)

    trend: list[dict[str, Any]] = [
        {
            "day": q.submitted_at.date().isoformat(),
            "estimate": estimate_cefr_from_score(q.cefr_level, q.score or 0.0),
        }
        for q in submitted_quizzes
    ] + [
        {"day": w.created_at.date().isoformat(), "estimate": w.cefr_estimate}
        for w in writings
        if w.cefr_estimate is not None
    ]
    trend.sort(key=lambda t: t["day"])

    tokens_in, tokens_out, cost_micro = (
        await db.execute(
            select(
                func.coalesce(func.sum(AIUsage.tokens_in), 0),
                func.coalesce(func.sum(AIUsage.tokens_out), 0),
                func.coalesce(func.sum(AIUsage.cost_micro_usd), 0),
            ).where(AIUsage.user_id == user.id)
        )
    ).one()

    by_model_rows = (
        await db.execute(
            select(AIUsage.model_used, func.sum(AIUsage.cost_micro_usd), func.count())
            .where(AIUsage.user_id == user.id)
            .group_by(AIUsage.model_used)
        )
    ).all()

    quota = await quota_state(str(user.id))

    # Recent spoken sessions — the progress page's speaking history.
    speaking_rows = (
        (
            await db.execute(
                select(SpeakingSession)
                .where(SpeakingSession.user_id == user.id)
                .order_by(SpeakingSession.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    return AnalysisResponse(
        cefr_level=user.cefr_level,
        skills=SkillsOut(**skills),
        counters=CountersOut(
            vocab_total=vocab_total,
            vocab_mastered=vocab_mastered,
            quizzes_taken=quizzes_taken,
            writings_submitted=writings_submitted,
            streak_days=streak,
        ),
        activity=activity,
        weak_spots=[WeakSpotOut(**w) for w in weak],
        cefr_trend=[CefrTrendPointOut(**t) for t in trend],
        speaking_sessions=[
            SpeakingSessionOut(
                id=str(r.id),
                scenario=r.scenario,
                cefr_level=r.cefr_level,
                turns=r.turns,
                overall=r.overall,
                grammar=r.grammar,
                fluency=r.fluency,
                feedback=r.feedback,
                created_at=r.created_at.isoformat(),
            )
            for r in speaking_rows
        ],
        usage=UsageOut(
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            cost_usd=round(cost_micro / 1_000_000, 6),
            by_model=[
                ByModelOut(model=m, cost_usd=round((c or 0) / 1_000_000, 6), calls=int(n))
                for m, c, n in by_model_rows
            ],
            quota=QuotaOut(**quota),
        ),
    )
