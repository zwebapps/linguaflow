"""Runs the golden set (`dataset.py`) through the real retriever and scores it.

Two layers of metric, per case:

1. Deterministic IR metrics (`metrics.py`) over the retrieved chunks' resolved
   document titles vs. `EvalCase.relevant_doc_titles` — no model call, never
   fails.
2. LLM-judged `faithfulness` + `answer_relevancy` (optional, `judge=True`):
   generate an answer from the retrieved context, then have a model score it.
   This is the only way to actually test the "says I'm not sure instead of
   confabulating" behaviour the two unanswerable golden-set cases exist for —
   the deterministic metrics alone can't see the generated text at all.

`app.rag.retriever` is imported as a MODULE (`rag_retriever`), not as a bare
`retrieve` function, so tests can monkeypatch `rag_retriever.retrieve` — same
convention as `app/api/v1/quiz.py` and `tests/test_assessment.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import router as ai_router
from app.ai.structured import parse_json_object
from app.ai.tasks import TaskType
from app.core.config import settings
from app.db.models import Document
from app.eval.dataset import GOLDEN_SET, EvalCase
from app.eval.metrics import context_precision, context_recall, hit_rate, mrr, ndcg_at_k
from app.rag import retriever as rag_retriever

log = structlog.get_logger(__name__)


# ── Prompts for the generate-then-judge half ─────────────────────────────────
#
# Kept local to this module rather than added to `app/ai/prompts.py` — that
# file is owned by another track and these prompts are eval-only, never sent
# from a real user-facing endpoint.

_ANSWER_SYSTEM_PROMPT = """\
You are a German-tutoring assistant answering ONE question using ONLY the \
context passages given to you. Answer in German, in 1-3 sentences.

If the context does not contain the answer, say so plainly in German \
(for example "Ich bin mir nicht sicher, das steht nicht in den Materialien.") \
instead of guessing or inventing a German grammar rule or fact you were not given.
"""

_JUDGE_SYSTEM_PROMPT = """\
You are grading one RAG answer for a German-tutoring app. Score two things on \
a 0.0-1.0 scale and return STRICT JSON — no prose, no markdown fences, nothing \
outside the JSON object:

- "faithfulness": is every claim in the answer supported by the context? \
1.0 = fully grounded in the context, 0.0 = pure invention. An honest "I'm not \
sure" when the context lacks the answer is fully faithful (1.0) — never \
penalise a correct refusal to guess.
- "answer_relevancy": does the answer actually address the question asked? \
1.0 = directly on point, 0.0 = off-topic or non-responsive.

Return ONLY: {"faithfulness": 0.0, "answer_relevancy": 0.0}
"""


class _JudgeScores(BaseModel):
    faithfulness: float
    answer_relevancy: float


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# ── Per-case / aggregate result shapes ───────────────────────────────────────


@dataclass(slots=True)
class CaseResult:
    question: str
    cefr_level: str
    relevant_doc_titles: list[str]
    retrieved_titles: list[str]
    hit_rate: float
    mrr: float
    ndcg: float
    context_precision: float
    context_recall: float
    generated_answer: str | None = None
    faithfulness: float | None = None
    answer_relevancy: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "cefr_level": self.cefr_level,
            "relevant_doc_titles": self.relevant_doc_titles,
            "retrieved_titles": self.retrieved_titles,
            "hit_rate": self.hit_rate,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "generated_answer": self.generated_answer,
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
        }


@dataclass(slots=True)
class EvalReport:
    strategy: str
    k: int
    n_cases: int
    rows: list[CaseResult] = field(default_factory=list)
    means: dict[str, float | None] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "k": self.k,
            "n_cases": self.n_cases,
            "rows": [r.as_dict() for r in self.rows],
            "means": self.means,
        }


# ── Document-id → title resolution ───────────────────────────────────────────


async def _resolve_titles(db: AsyncSession, document_ids: list[str]) -> dict[str, str]:
    """Look up canonical `Document.title` for a batch of retrieved chunk ids.

    Best-effort like the rest of the RAG surface (`retriever.py`'s own
    docstring: "never raises for no results") — a DB hiccup here degrades to
    an empty mapping (callers fall back to whatever title the retriever
    itself attached) rather than aborting the whole eval run over one lookup.
    """
    ids = sorted({str(d) for d in document_ids})
    if not ids:
        return {}
    try:
        rows = (
            await db.execute(select(Document.id, Document.title).where(Document.id.in_(ids)))
        ).all()
    except Exception as exc:
        log.warning("eval_title_lookup_failed", error=str(exc)[:200])
        return {}
    return {str(doc_id): title for doc_id, title in rows}


# ── Generate-then-judge ───────────────────────────────────────────────────────


async def _generate_answer(
    db: AsyncSession, *, question: str, context: str, user_id: Any | None
) -> str | None:
    messages: list[BaseMessage] = [
        SystemMessage(content=_ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
    ]
    try:
        result = await ai_router.complete(
            db, task_type=TaskType.CONVERSATION, messages=messages, user_id=user_id
        )
        return result.text
    except Exception as exc:
        # An eval run exists to survive flaky infra and still report the cases
        # that DID work — one dead model must not take down the whole report.
        log.warning("eval_answer_generation_failed", question=question[:80], error=str(exc)[:200])
        return None


async def _judge(
    db: AsyncSession, *, question: str, context: str, answer: str, user_id: Any | None
) -> tuple[float | None, float | None]:
    """Score `answer` for faithfulness + relevancy. One repair retry on bad
    JSON, same shape as `app.ai.structured._complete_structured`, but a
    failure here degrades to `(None, None)` for this one case instead of
    raising `UpstreamError` — a judge flake must never crash the eval run.
    """
    messages: list[BaseMessage] = [
        SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer: {answer}"),
    ]

    try:
        result = await ai_router.complete(
            db, task_type=TaskType.WRITING_EVALUATE, messages=messages, user_id=user_id
        )
    except Exception as exc:
        log.warning("eval_judge_call_failed", error=str(exc)[:200])
        return None, None

    try:
        scores = _JudgeScores.model_validate(parse_json_object(result.text))
    except (ValueError, ValidationError) as exc:
        log.warning("eval_judge_json_invalid", error=str(exc)[:200])
        messages.append(AIMessage(content=result.text))
        messages.append(
            HumanMessage(
                content=(
                    "Your previous response was not valid JSON matching the requested "
                    f"schema. Validation error: {exc}\n"
                    "Return ONLY the corrected JSON object — no prose, no markdown fences."
                )
            )
        )
        try:
            retry = await ai_router.complete(
                db, task_type=TaskType.WRITING_EVALUATE, messages=messages, user_id=user_id
            )
            scores = _JudgeScores.model_validate(parse_json_object(retry.text))
        except Exception as exc2:
            log.warning("eval_judge_repair_failed", error=str(exc2)[:200])
            return None, None

    return _clamp01(scores.faithfulness), _clamp01(scores.answer_relevancy)


# ── One case, one report ─────────────────────────────────────────────────────


async def _run_case(
    db: AsyncSession,
    case: EvalCase,
    *,
    k: int,
    strategy: str | None,
    judge: bool,
    user_id: Any | None,
) -> tuple[CaseResult, str]:
    result = await rag_retriever.retrieve(db, case.question, k=k, strategy=strategy)

    doc_ids = [r.document_id for r in result.results]
    titles_by_id = await _resolve_titles(db, doc_ids)
    # Deduplicate, preserving rank order. Retrieval is CHUNK-level, so six hits from
    # one document would otherwise appear as that title six times — and these are
    # DOCUMENT-level metrics. Left duplicated, DCG accumulated a gain per repeat
    # while IDCG normalised against a single relevant doc, producing nDCG of 3.3
    # (it is bounded by 1.0 by definition). Rank order is kept because MRR and nDCG
    # both depend on position.
    retrieved_titles: list[str] = []
    for r in result.results:
        title = titles_by_id.get(str(r.document_id), r.title)
        if title not in retrieved_titles:
            retrieved_titles.append(title)
    relevant = set(case.relevant_doc_titles)

    row = CaseResult(
        question=case.question,
        cefr_level=case.cefr_level,
        relevant_doc_titles=list(case.relevant_doc_titles),
        retrieved_titles=retrieved_titles,
        hit_rate=hit_rate(retrieved_titles, relevant, k),
        mrr=mrr(retrieved_titles, relevant),
        ndcg=ndcg_at_k(retrieved_titles, relevant, k),
        context_precision=context_precision(retrieved_titles, relevant, k),
        context_recall=context_recall(retrieved_titles, relevant, k),
    )

    if judge:
        context_text = "\n\n".join(c.text for c in result.results if c.text) or (
            "(kein Kontext gefunden)"
        )
        answer = await _generate_answer(
            db, question=case.question, context=context_text, user_id=user_id
        )
        row.generated_answer = answer
        if answer is not None:
            faithfulness, relevancy = await _judge(
                db, question=case.question, context=context_text, answer=answer, user_id=user_id
            )
            row.faithfulness = faithfulness
            row.answer_relevancy = relevancy

    return row, result.strategy


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _aggregate(rows: list[CaseResult]) -> dict[str, float | None]:
    return {
        "hit_rate": _mean([r.hit_rate for r in rows]),
        "mrr": _mean([r.mrr for r in rows]),
        "ndcg": _mean([r.ndcg for r in rows]),
        "context_precision": _mean([r.context_precision for r in rows]),
        "context_recall": _mean([r.context_recall for r in rows]),
        "faithfulness": _mean([r.faithfulness for r in rows if r.faithfulness is not None]),
        "answer_relevancy": _mean(
            [r.answer_relevancy for r in rows if r.answer_relevancy is not None]
        ),
    }


async def run_eval(
    db: AsyncSession,
    *,
    strategy: str | None = None,
    k: int | None = None,
    judge: bool = True,
    user_id: Any | None = None,
) -> EvalReport:
    """Run the whole golden set through `retriever.retrieve` (+ optionally the
    generate-then-judge pass) and aggregate into an `EvalReport`.

    `strategy=None` defers to `settings.SEARCH_STRATEGY` exactly like
    `retriever.retrieve` itself does — the *resolved* strategy name (as
    reported back by the retriever, which also collapses non-"dense" values
    to "hybrid") is what ends up on `EvalReport.strategy`, not the raw
    argument, so a report never lies about what actually ran.
    """
    resolved_k = k or settings.RETRIEVAL_TOP_K
    rows: list[CaseResult] = []
    resolved_strategy = strategy or settings.SEARCH_STRATEGY

    for case in GOLDEN_SET:
        row, resolved_strategy = await _run_case(
            db, case, k=resolved_k, strategy=strategy, judge=judge, user_id=user_id
        )
        rows.append(row)

    return EvalReport(
        strategy=resolved_strategy,
        k=resolved_k,
        n_cases=len(rows),
        rows=rows,
        means=_aggregate(rows),
    )
