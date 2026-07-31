"""CLI for the RAG evaluation harness (see `app/eval/runner.py`).

Run: `python -m scripts.eval_rag [--strategy hybrid|dense] [--k 6] [--no-judge] [--json out.json]`

With no `--strategy`, runs BOTH `hybrid` and `dense` and prints them side by
side — comparing retrieval strategies against each other is the actual point
of this exercise (does RRF fusion beat plain dense search on this corpus?),
not producing one isolated number.

Exits non-zero on an infrastructure failure — no `OPENROUTER_API_KEY` when
judging is requested, or zero documents ingested — with a clear one-line
message, never a bare traceback: this is meant to be runnable as a pre-flight
CI check, and a stack trace is a useless answer to "is the RAG pipeline OK".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.eval.runner import EvalReport, run_eval

_METRICS = (
    "hit_rate",
    "mrr",
    "ndcg",
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the RAG retriever (+ optional LLM judge) on the golden set."
    )
    parser.add_argument(
        "--strategy",
        choices=["hybrid", "dense"],
        default=None,
        help="Run one strategy only. Default: run both hybrid and dense and compare.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help=f"Top-k passed to the retriever (default: settings.RETRIEVAL_TOP_K="
        f"{settings.RETRIEVAL_TOP_K}).",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the LLM-judged faithfulness/answer_relevancy metrics (no model calls).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Also write the full report(s) to this JSON file.",
    )
    return parser.parse_args(argv)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def _print_table(reports: list[EvalReport]) -> None:
    header = f"{'metric':<20}" + "".join(f"{r.strategy:>14}" for r in reports)
    print(header)
    print("-" * len(header))
    for metric in _METRICS:
        row = f"{metric:<20}"
        for r in reports:
            row += f"{_fmt(r.means.get(metric)):>14}"
        print(row)
    print()
    for r in reports:
        print(f"[{r.strategy}] k={r.k} n_cases={r.n_cases}")


async def _preflight(*, judge: bool) -> str | None:
    """Return a human-readable problem description, or `None` if the run can proceed."""
    if judge and not settings.OPENROUTER_API_KEY:
        return (
            "OPENROUTER_API_KEY is not set — judging needs it for the answer-generation "
            "and faithfulness/answer_relevancy calls. Re-run with --no-judge to evaluate "
            "retrieval only, or set the key in backend/.env."
        )
    async with SessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    if count == 0:
        return (
            "No documents are ingested — retrieval has nothing to retrieve against. "
            "Run `python -m scripts.seed_kb` first."
        )
    return None


async def _run(args: argparse.Namespace) -> list[EvalReport]:
    strategies = [args.strategy] if args.strategy else ["hybrid", "dense"]
    reports: list[EvalReport] = []
    async with SessionLocal() as db:
        for strategy in strategies:
            report = await run_eval(db, strategy=strategy, k=args.k, judge=not args.no_judge)
            reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # ONE event loop for the whole run. Two `asyncio.run` calls create two loops,
    # and the SQLAlchemy async engine is a module-level singleton bound to whichever
    # loop touched it first — so the second call died with "attached to a different
    # loop", BM25 silently returned nothing, and the hybrid-vs-dense comparison was
    # measuring a degraded dense arm rather than the real one.
    async def _all() -> list[EvalReport]:
        problem = await _preflight(judge=not args.no_judge)
        if problem:
            print(f"eval_rag: {problem}", file=sys.stderr)
            sys.exit(1)
        return await _run(args)

    try:
        reports = asyncio.run(_all())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level CLI: report and exit, no traceback
        print(f"eval_rag failed: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_table(reports)

    if args.json:
        payload: Any = reports[0].as_dict() if len(reports) == 1 else [r.as_dict() for r in reports]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.json}")

    sys.exit(0)


if __name__ == "__main__":
    main()
