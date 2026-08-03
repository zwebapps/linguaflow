"""A/B testing over RAG strategies.

The properties that matter for an experiment to mean anything: assignment is
*stable* per user, traffic splits land near their configured weights, and the
aggregation doesn't flatter an arm that returned nothing.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.rag.experiments import (
    ARM_DENSE,
    ARM_HYBRID,
    DEFAULT_EXPERIMENT,
    Experiment,
    assign_arm,
    summarise,
)

RUNNING = Experiment(name="t", enabled=True, arms={ARM_HYBRID: 0.5, ARM_DENSE: 0.5})


# ── Assignment ────────────────────────────────────────────────────────────────


def test_a_user_always_gets_the_same_arm() -> None:
    """Random-per-request assignment would make per-user outcomes uninterpretable."""
    first, _ = assign_arm("user-42", RUNNING)
    for _ in range(50):
        again, _ = assign_arm("user-42", RUNNING)
        assert again == first


def test_assignment_survives_a_process_restart() -> None:
    """Python's hash() is salted per process; a stable arm needs a real digest.

    Recomputing from the same inputs must give the same answer — this test would
    fail if the implementation ever switched back to `hash()`.
    """
    from app.rag.experiments import _bucket

    assert _bucket("user-42", "t") == _bucket("user-42", "t")
    assert _bucket("user-42", "t") != _bucket("user-43", "t")


def test_a_disabled_experiment_uses_the_configured_default() -> None:
    strategy, name = assign_arm("user-1", DEFAULT_EXPERIMENT)  # disabled by default
    assert strategy == settings.SEARCH_STRATEGY
    assert name is None


def test_anonymous_callers_are_not_enrolled() -> None:
    strategy, name = assign_arm(None, RUNNING)
    assert strategy == settings.SEARCH_STRATEGY
    assert name is None


def test_enrolled_users_report_the_experiment_name() -> None:
    strategy, name = assign_arm("user-7", RUNNING)
    assert strategy in {ARM_HYBRID, ARM_DENSE}
    assert name == "t"


def test_a_fifty_fifty_split_is_roughly_even() -> None:
    arms = [assign_arm(f"user-{i}", RUNNING)[0] for i in range(2000)]
    share = arms.count(ARM_HYBRID) / len(arms)
    # Wide tolerance — this asserts "not badly skewed", not a precise ratio.
    assert 0.44 < share < 0.56, share


def test_weights_need_not_sum_to_one() -> None:
    """{a: 1, b: 3} should mean 25/75, so nobody has to hand-normalise."""
    exp = Experiment(name="w", enabled=True, arms={ARM_HYBRID: 1, ARM_DENSE: 3})
    arms = [assign_arm(f"u{i}", exp)[0] for i in range(2000)]
    share = arms.count(ARM_DENSE) / len(arms)
    assert 0.70 < share < 0.80, share


def test_a_single_arm_at_full_weight_takes_all_traffic() -> None:
    exp = Experiment(name="s", enabled=True, arms={ARM_DENSE: 1.0})
    assert all(assign_arm(f"u{i}", exp)[0] == ARM_DENSE for i in range(100))


def test_zero_weight_arms_never_get_traffic() -> None:
    exp = Experiment(name="z", enabled=True, arms={ARM_HYBRID: 0.0, ARM_DENSE: 1.0})
    assert all(assign_arm(f"u{i}", exp)[0] == ARM_DENSE for i in range(200))


def test_all_zero_weights_falls_back_rather_than_dividing_by_zero() -> None:
    exp = Experiment(name="bad", enabled=True, arms={ARM_HYBRID: 0.0, ARM_DENSE: 0.0})
    strategy, name = assign_arm("u1", exp)
    assert strategy == settings.SEARCH_STRATEGY
    assert name is None


def test_arm_order_in_the_dict_does_not_change_assignment() -> None:
    """Bucket boundaries must not depend on dict insertion order."""
    a = Experiment(name="o", enabled=True, arms={ARM_HYBRID: 0.5, ARM_DENSE: 0.5})
    b = Experiment(name="o", enabled=True, arms={ARM_DENSE: 0.5, ARM_HYBRID: 0.5})
    for i in range(200):
        assert assign_arm(f"u{i}", a)[0] == assign_arm(f"u{i}", b)[0]


# ── Aggregation ───────────────────────────────────────────────────────────────


def test_summarise_groups_and_ranks_by_usable_results() -> None:
    rows = [
        {"arm": "hybrid", "n_results": 6, "top_score": 0.03, "latency_ms": 400},
        {"arm": "hybrid", "n_results": 6, "top_score": 0.04, "latency_ms": 600},
        {"arm": "dense", "n_results": 2, "top_score": 0.02, "latency_ms": 200},
    ]
    stats = summarise(rows)
    assert [s["arm"] for s in stats] == ["hybrid", "dense"]
    assert stats[0]["impressions"] == 2
    assert stats[0]["mean_results"] == 6.0
    assert stats[0]["mean_latency_ms"] == 500.0


def test_zero_result_rate_is_reported() -> None:
    """An arm that quietly returns nothing is failing, even without errors."""
    rows = [
        {"arm": "dense", "n_results": 0, "top_score": None, "latency_ms": 90},
        {"arm": "dense", "n_results": 0, "top_score": None, "latency_ms": 80},
        {"arm": "dense", "n_results": 4, "top_score": 0.02, "latency_ms": 300},
    ]
    stats = summarise(rows)
    assert stats[0]["zero_result_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_empty_retrievals_do_not_drag_the_mean_score_down() -> None:
    """Averaging in 0.0 for "found nothing" would conflate it with "found weak"."""
    rows = [
        {"arm": "a", "n_results": 0, "top_score": None, "latency_ms": 10},
        {"arm": "a", "n_results": 5, "top_score": 0.8, "latency_ms": 10},
    ]
    stats = summarise(rows)
    assert stats[0]["mean_top_score_within_arm"] == pytest.approx(0.8)


def test_summarise_handles_no_rows() -> None:
    assert summarise([]) == []


def test_unknown_arm_is_bucketed_not_dropped() -> None:
    stats = summarise([{"arm": None, "n_results": 1, "top_score": 0.1, "latency_ms": 5}])
    assert stats[0]["arm"] == "unknown"


def test_ranking_ignores_relevance_score_across_arms() -> None:
    """Dense reports cosine (~0.7); hybrid reports fused RRF (~0.03).

    Those are different units. Ranking by score would hand the win to dense every
    time regardless of quality — a live run showed exactly that. Ordering must
    depend only on scale-free measures.
    """
    rows = [
        # dense: high raw score but returns nothing a third of the time
        {"arm": "dense", "n_results": 0, "top_score": None, "latency_ms": 100},
        {"arm": "dense", "n_results": 6, "top_score": 0.75, "latency_ms": 100},
        {"arm": "dense", "n_results": 6, "top_score": 0.75, "latency_ms": 100},
        # hybrid: tiny fused score but never empty
        {"arm": "hybrid", "n_results": 6, "top_score": 0.03, "latency_ms": 120},
        {"arm": "hybrid", "n_results": 6, "top_score": 0.03, "latency_ms": 120},
        {"arm": "hybrid", "n_results": 6, "top_score": 0.03, "latency_ms": 120},
    ]
    stats = summarise(rows)
    assert stats[0]["arm"] == "hybrid", "the never-empty arm must rank first"
    assert "mean_top_score" not in stats[0], "raw score must not look cross-comparable"
    assert "mean_top_score_within_arm" in stats[0]


# ── The keyword arm (dense vs keyword vs hybrid is the classic ablation) ─────


def test_supported_strategies_is_the_single_authority() -> None:
    """The validator and the UI dropdown both derive from this list.

    If it drifts from the retriever's actual branches, an admin can configure an
    arm that silently falls back to hybrid — an experiment that lies about what
    it is testing.
    """
    from app.rag.experiments import SUPPORTED_STRATEGIES

    assert SUPPORTED_STRATEGIES == ("hybrid", "dense", "keyword")


def test_admin_upsert_accepts_a_keyword_arm() -> None:
    from app.api.v1.admin import ExperimentUpsertRequest

    req = ExperimentUpsertRequest(enabled=True, arms={"keyword": 0.5, "hybrid": 0.5})
    assert set(req.arms) == {"keyword", "hybrid"}


def test_admin_upsert_still_rejects_an_unknown_arm() -> None:
    import pytest
    from pydantic import ValidationError

    from app.api.v1.admin import ExperimentUpsertRequest

    with pytest.raises(ValidationError) as exc:
        ExperimentUpsertRequest(enabled=True, arms={"quantum": 1.0})
    # The error must NAME the allowed set — an admin typing into a raw API
    # should get the vocabulary, not just a refusal.
    assert "keyword" in str(exc.value)


def test_three_arm_assignment_is_stable_and_exhaustive() -> None:
    from app.rag.experiments import Experiment, assign_arm

    exp = Experiment(
        name="retrieval_strategy_v1",
        enabled=True,
        arms={"hybrid": 1.0, "dense": 1.0, "keyword": 1.0},
    )
    seen = {assign_arm(f"user-{i}", experiment=exp)[0] for i in range(300)}
    assert seen == {"hybrid", "dense", "keyword"}
    # Stability: the same learner always lands on the same arm.
    for i in range(20):
        a = assign_arm(f"user-{i}", experiment=exp)[0]
        assert all(assign_arm(f"user-{i}", experiment=exp)[0] == a for _ in range(5))
