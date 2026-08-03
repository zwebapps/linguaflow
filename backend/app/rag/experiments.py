"""A/B testing for RAG strategies.

Two different questions are being answered here, and conflating them is how A/B
tests end up meaningless:

1. **Which strategy does *this* request use?** Answered by a *deterministic* hash
   of the user id — the same learner always gets the same arm. Random per-request
   assignment would let one learner see hybrid on one question and dense on the
   next, which makes per-user outcome data uninterpretable and the experience
   inconsistent.
2. **Which arm is winning?** Answered by aggregating outcomes recorded against the
   arm that served each request (`rag_events`), not by re-running retrieval.

The split is config, so an admin can shift traffic or stop an experiment without a
redeploy — same principle as the AI-route table.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

# Bucketing salt. Changing it re-randomises assignment, which invalidates a
# running experiment — so it is a constant, not a setting someone tunes casually.
_BUCKET_SALT = "linguaflow-rag-ab-v1"

# Arms are named by the retrieval strategy they select. SUPPORTED_STRATEGIES is
# the single authority — the admin validator and the UI's dropdown both derive
# from it, so adding a strategy here is the ONLY step that widens the vocabulary
# everywhere. Keep in sync with `settings.SEARCH_STRATEGY`'s Literal.
ARM_HYBRID = "hybrid"
ARM_DENSE = "dense"
ARM_KEYWORD = "keyword"

SUPPORTED_STRATEGIES: tuple[str, ...] = (ARM_HYBRID, ARM_DENSE, ARM_KEYWORD)


@dataclass(slots=True)
class Experiment:
    """A running split test over retrieval strategies."""

    name: str
    enabled: bool
    # arm name → traffic share (0.0–1.0). Shares are normalised, so {a:1, b:1}
    # means 50/50 and nobody has to keep them summing to exactly 1.
    arms: dict[str, float] = field(default_factory=dict)

    def normalised(self) -> list[tuple[str, float]]:
        total = sum(v for v in self.arms.values() if v > 0)
        if total <= 0:
            return []
        # Sorted for determinism: dict order must not change bucket boundaries.
        return [(k, v / total) for k, v in sorted(self.arms.items()) if v > 0]


# Default experiment: an even split between hybrid and dense retrieval. Disabled
# by default so normal operation is unaffected until someone opts in.
DEFAULT_EXPERIMENT = Experiment(
    name="retrieval_strategy_v1",
    enabled=False,
    arms={ARM_HYBRID: 0.5, ARM_DENSE: 0.5},
)


def _bucket(user_key: str, experiment: str) -> float:
    """Stable [0,1) position for a user within an experiment.

    SHA-256 rather than Python's `hash()`: `hash()` is salted per process, so
    assignment would change every restart and a "stable" arm wouldn't be stable.
    """
    digest = hashlib.sha256(f"{_BUCKET_SALT}:{experiment}:{user_key}".encode()).digest()
    # 8 bytes is ample resolution and avoids big-int work.
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def assign_arm(
    user_key: str | None,
    experiment: Experiment | None = None,
) -> tuple[str, str | None]:
    """→ (strategy, experiment_name). `experiment_name` is None when not enrolled.

    Falls back to the configured default strategy when the experiment is off or
    the caller is anonymous, so retrieval always has a valid strategy.
    """
    exp = experiment or DEFAULT_EXPERIMENT
    if not exp.enabled or not user_key:
        return settings.SEARCH_STRATEGY, None

    arms = exp.normalised()
    if not arms:
        return settings.SEARCH_STRATEGY, None

    position = _bucket(str(user_key), exp.name)
    cumulative = 0.0
    for arm, share in arms:
        cumulative += share
        if position < cumulative:
            return arm, exp.name
    # Floating-point drift on the last boundary — award the final arm.
    return arms[-1][0], exp.name


async def load_experiment(db: Any, name: str | None = None) -> Experiment:
    """Read the experiment from the DB, falling back to the shipped default.

    Best-effort: a missing table or a DB hiccup must not break retrieval, so any
    failure returns the (disabled) default rather than raising.
    """
    from app.db.models import ExperimentConfig

    target = name or DEFAULT_EXPERIMENT.name
    try:
        row = await db.get(ExperimentConfig, target)
    except Exception as exc:
        log.warning("experiment_load_failed", experiment=target, error=str(exc)[:200])
        return DEFAULT_EXPERIMENT

    if row is None:
        return DEFAULT_EXPERIMENT

    arms = {str(k): float(v) for k, v in (row.arms or {}).items()}
    return Experiment(name=row.name, enabled=bool(row.enabled), arms=arms)


async def record_event(
    db: Any,
    *,
    user_id: Any | None,
    experiment: str | None,
    arm: str,
    strategy: str,
    query: str,
    n_results: int,
    top_score: float | None,
    latency_ms: int,
) -> None:
    """Persist one retrieval outcome. Never raises — telemetry must not break UX."""
    from app.db.models import RagEvent

    try:
        db.add(
            RagEvent(
                user_id=user_id,
                experiment=experiment,
                arm=arm,
                strategy=strategy,
                query=(query or "")[:500],
                n_results=n_results,
                top_score=top_score,
                latency_ms=latency_ms,
            )
        )
        await db.commit()
    except Exception as exc:
        log.warning("rag_event_record_failed", error=str(exc)[:200])


@dataclass(slots=True)
class ArmStats:
    arm: str
    impressions: int = 0
    # Mean retrieved-result count: an arm that returns nothing is failing even if
    # it never errors.
    mean_results: float = 0.0
    mean_top_score: float = 0.0
    mean_latency_ms: float = 0.0
    zero_result_rate: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "impressions": self.impressions,
            "mean_results": round(self.mean_results, 3),
            # NOT comparable between arms — see `summarise`. Reported for
            # within-arm trend only, and labelled so nobody reads it as a ranking.
            "mean_top_score_within_arm": round(self.mean_top_score, 5),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
            "zero_result_rate": round(self.zero_result_rate, 4),
        }


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate raw per-request rows into per-arm stats.

    Pure so it can be unit-tested without a database. `rows` items need
    `arm`, `n_results`, `top_score`, `latency_ms`.

    **Ranking deliberately ignores relevance score.** Dense retrieval reports raw
    cosine similarity (~0.7) while hybrid reports a fused Reciprocal-Rank score
    (~0.03); they are different units, so ordering arms by score would always
    "prove" dense wins. A live run showed exactly that. Ranking therefore uses only
    scale-free measures — how often an arm returned nothing, then how many usable
    results it returned — and the score is surfaced for within-arm trends only.

    Judging *relevance quality* across arms needs the offline eval harness
    (`app/eval/`), which scores both arms against the same labelled golden set.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault(str(r.get("arm") or "unknown"), []).append(r)

    out: list[ArmStats] = []
    for arm, items in buckets.items():
        n = len(items)
        if not n:
            continue
        results = [int(i.get("n_results") or 0) for i in items]
        scores = [float(i.get("top_score") or 0.0) for i in items]
        lats = [float(i.get("latency_ms") or 0.0) for i in items]
        out.append(
            ArmStats(
                arm=arm,
                impressions=n,
                mean_results=sum(results) / n,
                # Mean over hits only: averaging in zeros from empty retrievals
                # would conflate "found nothing" with "found something weak".
                mean_top_score=(
                    sum(s for s in scores if s > 0) / max(1, len([s for s in scores if s > 0]))
                ),
                mean_latency_ms=sum(lats) / n,
                zero_result_rate=len([r for r in results if r == 0]) / n,
            )
        )

    # Scale-free ordering only: fewest empty retrievals first, then most usable
    # results. Score is excluded on purpose (see the docstring).
    out.sort(key=lambda a: (-a.zero_result_rate, a.mean_results), reverse=True)
    return [a.as_dict() for a in out]
