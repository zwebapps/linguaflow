"""Hermetic tests for the RAG evaluation harness (`app/eval/*`).

No network, no live LLM, no Postgres:

  * `app.rag.retriever.retrieve` is monkeypatched at its *defining* module
    (`rag_retriever`), same convention as `tests/test_assessment.py`.
  * `app.ai.router.complete` is monkeypatched at its defining module, same
    convention as `tests/test_tools.py` / `tests/test_assessment.py`.
  * A tiny in-memory `_FakeSession` (same shape as `test_admin_library.py`'s
    `FakeSession`) stands in for `AsyncSession` for the `Document` title lookup.

Covers: every metrics.py formula on a known-answer case (nDCG computed by
hand, independently of the implementation, in the test itself) plus every
degenerate case named in the task brief; the runner's aggregation; a judge
exception degrading to `None` without crashing the run; and that the golden
set actually contains the two required unanswerable cases.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.ai.router import AIResult
from app.ai.tasks import TaskType
from app.core.errors import AllModelsFailed, UpstreamError
from app.eval import runner as eval_runner
from app.eval.dataset import GOLDEN_SET, EvalCase
from app.eval.metrics import (
    context_precision,
    context_recall,
    hit_rate,
    mrr,
    ndcg_at_k,
)
from app.rag.contracts import RetrievedChunk, SearchResult

# asyncio_mode = "auto" (pyproject.toml) — plain `async def test_...` works with no marker.


# ── hit_rate ─────────────────────────────────────────────────────────────────


def test_hit_rate_true_when_a_relevant_doc_is_within_top_k() -> None:
    assert hit_rate(["a", "b", "c"], {"b"}, 3) == 1.0


def test_hit_rate_false_when_the_only_relevant_doc_is_outside_top_k() -> None:
    assert hit_rate(["a", "b", "c"], {"c"}, 2) == 0.0


def test_hit_rate_empty_retrieved_is_zero() -> None:
    assert hit_rate([], {"a"}, 5) == 0.0


def test_hit_rate_empty_relevant_is_zero() -> None:
    assert hit_rate(["a", "b"], set(), 5) == 0.0


def test_hit_rate_k_zero_is_zero() -> None:
    assert hit_rate(["a"], {"a"}, 0) == 0.0


def test_hit_rate_k_larger_than_list_is_fine() -> None:
    assert hit_rate(["a", "b"], {"b"}, 100) == 1.0


# ── mrr ──────────────────────────────────────────────────────────────────────


def test_mrr_hit_at_first_position() -> None:
    assert mrr(["a", "b", "c"], {"a"}) == 1.0


def test_mrr_hit_at_second_position() -> None:
    assert mrr(["a", "b", "c"], {"b"}) == pytest.approx(0.5)


def test_mrr_hit_at_third_position() -> None:
    assert mrr(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)


def test_mrr_no_hit_is_zero() -> None:
    assert mrr(["a", "b"], {"z"}) == 0.0


def test_mrr_empty_retrieved_is_zero() -> None:
    assert mrr([], {"a"}) == 0.0


def test_mrr_empty_relevant_is_zero() -> None:
    assert mrr(["a"], set()) == 0.0


def test_mrr_is_not_truncated_by_any_k_a_hit_past_a_typical_k_still_counts() -> None:
    # MRR has no `k` parameter at all — this is the point being tested: a hit
    # buried at rank 9 is not zero, unlike hit_rate(..., k=5) would report.
    retrieved = [str(i) for i in range(10)]
    assert mrr(retrieved, {"8"}) == pytest.approx(1 / 9)


# ── ndcg_at_k ────────────────────────────────────────────────────────────────


def test_ndcg_at_k_matches_a_hand_computed_value() -> None:
    """Cross-check against the formula computed independently here, not by
    calling into the implementation a second time.
    """
    retrieved = ["a", "b", "c", "d"]
    relevant = {"b", "d"}  # hits land at ranks 2 and 4
    k = 4

    dcg = 1 / math.log2(2 + 1) + 1 / math.log2(4 + 1)
    # Ideal ranking packs both relevant docs at ranks 1 and 2.
    idcg = 1 / math.log2(1 + 1) + 1 / math.log2(2 + 1)
    expected = dcg / idcg

    assert ndcg_at_k(retrieved, relevant, k) == pytest.approx(expected)


def test_ndcg_at_k_perfect_ranking_scores_one() -> None:
    assert ndcg_at_k(["a", "b", "c"], {"a", "b"}, 3) == pytest.approx(1.0)


def test_ndcg_at_k_worst_ranking_scores_less_than_one() -> None:
    # Same docs, relevant one pushed to the back — must score strictly worse
    # than the perfect-ranking case above.
    assert ndcg_at_k(["c", "b", "a"], {"a", "b"}, 3) < 1.0


def test_ndcg_at_k_no_relevant_docs_is_zero() -> None:
    assert ndcg_at_k(["a", "b"], set(), 2) == 0.0


def test_ndcg_at_k_empty_retrieved_is_zero() -> None:
    assert ndcg_at_k([], {"a"}, 3) == 0.0


def test_ndcg_at_k_zero_k_is_zero() -> None:
    assert ndcg_at_k(["a"], {"a"}, 0) == 0.0


def test_ndcg_at_k_larger_than_list_behaves_like_the_full_list() -> None:
    retrieved = ["a", "b"]
    relevant = {"a"}
    assert ndcg_at_k(retrieved, relevant, 100) == ndcg_at_k(retrieved, relevant, 2)


# ── context_precision ────────────────────────────────────────────────────────


def test_context_precision_basic_fraction() -> None:
    assert context_precision(["a", "b", "c"], {"a", "c"}, 3) == pytest.approx(2 / 3)


def test_context_precision_k_narrows_the_window() -> None:
    assert context_precision(["a", "b", "c"], {"a"}, 1) == 1.0


def test_context_precision_empty_retrieved_is_zero_not_vacuously_perfect() -> None:
    assert context_precision([], {"a"}, 3) == 0.0


def test_context_precision_k_zero_is_zero() -> None:
    assert context_precision(["a"], {"a"}, 0) == 0.0


# ── context_recall ───────────────────────────────────────────────────────────


def test_context_recall_basic_fraction() -> None:
    assert context_recall(["a", "b"], {"a", "b", "c"}, 5) == pytest.approx(2 / 3)


def test_context_recall_k_caps_the_search_window() -> None:
    # Only "a" is inside the top-1 window; "d" is relevant but never surfaces.
    assert context_recall(["a", "b", "c"], {"a", "d"}, 1) == pytest.approx(0.5)


def test_context_recall_empty_relevant_is_zero_not_vacuously_perfect() -> None:
    assert context_recall(["a"], set(), 3) == 0.0


def test_context_recall_finds_everything_scores_one() -> None:
    assert context_recall(["a", "b"], {"a", "b"}, 5) == 1.0


# ── dataset.py — the golden set itself ───────────────────────────────────────


def test_golden_set_has_between_ten_and_fourteen_cases() -> None:
    assert 10 <= len(GOLDEN_SET) <= 14


def test_golden_set_has_exactly_two_unanswerable_cases() -> None:
    unanswerable = [c for c in GOLDEN_SET if not c.relevant_doc_titles]
    assert len(unanswerable) == 2
    for case in unanswerable:
        assert any(
            kw in case.expected_answer_contains for kw in ("nicht sicher", "weiß nicht", "kein")
        )


def test_golden_set_relevant_titles_match_the_seeded_document_titles() -> None:
    from app.services.seed_kb import SEED_DOCS

    seeded_titles = {d.title for d in SEED_DOCS}
    for case in GOLDEN_SET:
        for title in case.relevant_doc_titles:
            assert title in seeded_titles


def test_golden_set_every_case_has_a_question_and_a_cefr_level() -> None:
    for case in GOLDEN_SET:
        assert case.question.strip()
        assert case.cefr_level in {"A1", "A2", "B1", "B2", "C1"}


# ── Test doubles for the runner ───────────────────────────────────────────────


class _FakeDocResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeSession:
    """Just enough `AsyncSession` surface for `runner._resolve_titles`."""

    def __init__(self, doc_rows: list[tuple[str, str]] | None = None) -> None:
        self._doc_rows = doc_rows or []

    async def execute(self, _stmt: Any) -> _FakeDocResult:
        return _FakeDocResult(self._doc_rows)


class _ExplodingSession:
    async def execute(self, _stmt: Any) -> Any:
        raise AssertionError("should never query the DB for an empty id batch")


class _BrokenSession:
    async def execute(self, _stmt: Any) -> Any:
        raise RuntimeError("db is down")


def _fake_ai_result(text: str) -> AIResult:
    return AIResult(text=text, model_used="fake/judge-model")


def _chunk(doc_id: str, title: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=f"chunk-{doc_id}", document_id=doc_id, title=title, text=text, snippet=text, score=1.0
    )


_CASE_A = EvalCase(
    question="q1",
    expected_answer_contains=["x"],
    relevant_doc_titles=["Doc A"],
    cefr_level="A1",
)
_CASE_B = EvalCase(
    question="q2",
    expected_answer_contains=["y"],
    relevant_doc_titles=["Doc B"],
    cefr_level="A2",
)


async def _fake_retrieve_a_hits_b_misses(
    _db: Any, query: str, *, k: int | None = None, strategy: str | None = None, **_kw: Any
) -> SearchResult:
    """`q1` retrieves the doc that IS relevant (a hit); `q2` retrieves a doc
    that is NOT the relevant one (a miss) — gives every deterministic metric
    something non-trivial to disagree about.
    """
    if query == "q1":
        chunks = [_chunk("id-a", "Doc A", "context about a")]
    else:
        chunks = [_chunk("id-x", "Doc X", "unrelated context")]
    return SearchResult(query=query, strategy=strategy or "hybrid", results=chunks, took_ms=1)


# ── _resolve_titles ────────────────────────────────────────────────────────────


async def test_resolve_titles_maps_ids_to_db_titles() -> None:
    db = _FakeSession(doc_rows=[("id-1", "Real Title")])
    mapping = await eval_runner._resolve_titles(db, ["id-1", "id-1"])
    assert mapping == {"id-1": "Real Title"}


async def test_resolve_titles_empty_ids_skips_the_db_entirely() -> None:
    mapping = await eval_runner._resolve_titles(_ExplodingSession(), [])
    assert mapping == {}


async def test_resolve_titles_db_failure_degrades_to_empty_mapping() -> None:
    mapping = await eval_runner._resolve_titles(_BrokenSession(), ["id-1"])
    assert mapping == {}


# ── run_eval — deterministic half ────────────────────────────────────────────


async def test_run_eval_without_judge_aggregates_deterministic_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A, _CASE_B])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", _fake_retrieve_a_hits_b_misses)

    async def _complete_must_not_be_called(*_a: Any, **_kw: Any) -> AIResult:
        raise AssertionError("ai_router.complete must not run when judge=False")

    monkeypatch.setattr(eval_runner.ai_router, "complete", _complete_must_not_be_called)

    db = _FakeSession(doc_rows=[("id-a", "Doc A"), ("id-x", "Doc X")])
    report = await eval_runner.run_eval(db, strategy="hybrid", k=5, judge=False)

    assert report.strategy == "hybrid"
    assert report.k == 5
    assert report.n_cases == 2

    row_a, row_b = report.rows
    assert row_a.hit_rate == 1.0  # "Doc A" retrieved, and it IS relevant
    assert row_b.hit_rate == 0.0  # "Doc X" retrieved, "Doc B" is relevant — miss
    assert report.means["hit_rate"] == pytest.approx(0.5)

    # judge=False: no generation, no judged scores, no crash.
    assert row_a.generated_answer is None
    assert row_a.faithfulness is None
    assert report.means["faithfulness"] is None
    assert report.means["answer_relevancy"] is None


async def test_run_eval_resolves_titles_from_the_document_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retriever's own `RetrievedChunk.title` is deliberately wrong here
    ("Stale Title") — the DB lookup must win, proving `run_eval` actually
    calls `_resolve_titles` rather than trusting the retriever's title.
    """

    async def fake_retrieve(_db: Any, query: str, **_kw: Any) -> SearchResult:
        return SearchResult(
            query=query,
            strategy="hybrid",
            results=[_chunk("id-a", "Stale Title", "context")],
            took_ms=1,
        )

    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", fake_retrieve)

    db = _FakeSession(doc_rows=[("id-a", "Doc A")])
    report = await eval_runner.run_eval(db, strategy="hybrid", k=5, judge=False)

    assert report.rows[0].retrieved_titles == ["Doc A"]
    assert report.rows[0].hit_rate == 1.0


# ── run_eval — LLM-judged half ────────────────────────────────────────────────


async def test_run_eval_with_judge_generates_an_answer_and_scores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", _fake_retrieve_a_hits_b_misses)

    calls: list[str] = []

    async def fake_complete(
        _db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        calls.append(str(task_type))
        if task_type == TaskType.CONVERSATION:
            return _fake_ai_result("Das ist eine Testantwort.")
        return _fake_ai_result('{"faithfulness": 0.9, "answer_relevancy": 0.8}')

    monkeypatch.setattr(eval_runner.ai_router, "complete", fake_complete)

    db = _FakeSession(doc_rows=[("id-a", "Doc A")])
    report = await eval_runner.run_eval(db, strategy="hybrid", k=5, judge=True)

    assert calls == [str(TaskType.CONVERSATION), str(TaskType.WRITING_EVALUATE)]
    row = report.rows[0]
    assert row.generated_answer == "Das ist eine Testantwort."
    assert row.faithfulness == pytest.approx(0.9)
    assert row.answer_relevancy == pytest.approx(0.8)
    assert report.means["faithfulness"] == pytest.approx(0.9)


async def test_run_eval_judge_repairs_once_after_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", _fake_retrieve_a_hits_b_misses)

    judge_calls: list[str] = []

    async def fake_complete(
        _db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        if task_type == TaskType.CONVERSATION:
            return _fake_ai_result("Antwort.")
        judge_calls.append(str(task_type))
        if len(judge_calls) == 1:
            return _fake_ai_result("this is not { valid json at all")
        return _fake_ai_result('{"faithfulness": 0.5, "answer_relevancy": 0.6}')

    monkeypatch.setattr(eval_runner.ai_router, "complete", fake_complete)

    db = _FakeSession(doc_rows=[("id-a", "Doc A")])
    report = await eval_runner.run_eval(db, judge=True)

    assert len(judge_calls) == 2  # exactly one repair retry
    assert report.rows[0].faithfulness == pytest.approx(0.5)
    assert report.rows[0].answer_relevancy == pytest.approx(0.6)


async def test_run_eval_judge_failure_leaves_none_and_does_not_crash_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A, _CASE_B])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", _fake_retrieve_a_hits_b_misses)

    async def fake_complete(
        _db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        if task_type == TaskType.CONVERSATION:
            return _fake_ai_result("Antwort.")
        raise AllModelsFailed("every judge model is down")

    monkeypatch.setattr(eval_runner.ai_router, "complete", fake_complete)

    db = _FakeSession(doc_rows=[("id-a", "Doc A"), ("id-x", "Doc X")])
    report = await eval_runner.run_eval(db, judge=True)  # must not raise

    assert report.n_cases == 2  # both cases still completed
    for row in report.rows:
        assert row.generated_answer == "Antwort."
        assert row.faithfulness is None
        assert row.answer_relevancy is None
    assert report.means["faithfulness"] is None
    assert report.means["answer_relevancy"] is None


async def test_run_eval_answer_generation_failure_skips_the_judge_call_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runner, "GOLDEN_SET", [_CASE_A])
    monkeypatch.setattr(eval_runner.rag_retriever, "retrieve", _fake_retrieve_a_hits_b_misses)

    async def fake_complete(
        _db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        if task_type == TaskType.CONVERSATION:
            raise UpstreamError("model down")
        raise AssertionError("the judge must never run if there is no answer to judge")

    monkeypatch.setattr(eval_runner.ai_router, "complete", fake_complete)

    db = _FakeSession(doc_rows=[("id-a", "Doc A")])
    report = await eval_runner.run_eval(db, judge=True)  # must not raise

    row = report.rows[0]
    assert row.generated_answer is None
    assert row.faithfulness is None
    assert row.answer_relevancy is None
