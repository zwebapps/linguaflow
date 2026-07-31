"""Deterministic retrieval metrics for the RAG evaluation harness.

See `runner.py` for the other half — LLM-judged `faithfulness` and
`answer_relevancy`, which need a live model and therefore can't be pure
functions.

We deliberately do NOT depend on the `ragas` package: it is uninstalled in
this venv and, as of this writing, incompatible with our pinned LangChain 1.x
(`ragas` imports `langchain_community.chat_models.vertexai`, which no longer
exists in current `langchain-community` — verified 2026-07-31, `pip install
ragas` resolves but `import ragas` then fails at import time). The task brief
explicitly allows "RAGAs or otherwise", so this module is the "otherwise":
the same standard IR metrics RAGAs would compute, implemented as small,
dependency-free, unit-testable functions. Do not re-add `ragas` to solve a
gap here — it will not import.

Every function is pure (no IO, no randomness, no logging) and works over
plain sequences of ids (chunk ids, document ids, or resolved document titles
— `runner.py` decides which). Relevance is binary throughout: an id either is
or isn't in the caller's `relevant` set. The golden set in `dataset.py` has no
graded relevance judgments, so a richer scale would be unearned precision.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def _relevant_set(relevant: Iterable[str]) -> set[str]:
    return set(relevant)


def _dedupe(retrieved: Sequence[str]) -> list[str]:
    """Collapse repeats, keeping first-seen rank order.

    These are DOCUMENT-level metrics, but retrieval is CHUNK-level — several hits
    routinely resolve to the same document. Counted once per chunk, DCG gains a
    point per repeat while IDCG normalises against the distinct relevant set, and
    nDCG climbs above 1.0 (observed: 3.3), which is meaningless by definition.
    Guarding here as well as at the call site means no caller can reproduce it.
    """
    seen: set[str] = set()
    out: list[str] = []
    for doc in retrieved:
        if doc not in seen:
            seen.add(doc)
            out.append(doc)
    return out


def hit_rate(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """1.0 if any of the top-`k` retrieved ids is relevant, else 0.0.

    Formula: ``1[ ∃ d ∈ retrieved[:k] : d ∈ relevant ]``.

    Degenerate cases resolve to 0.0 rather than raising: an empty `retrieved`
    has nothing to hit with; an empty `relevant` has nothing to be hit; `k`
    larger than `len(retrieved)` just means the slice is the whole list;
    `k <= 0` means "look at nothing", which can't hit either.
    """
    rel = _relevant_set(relevant)
    retrieved = _dedupe(retrieved)
    if not rel or not retrieved or k <= 0:
        return 0.0
    return 1.0 if any(doc in rel for doc in retrieved[:k]) else 0.0


def mrr(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant hit anywhere in `retrieved`.

    Formula: ``1 / rank_of_first_hit`` (1-indexed), or 0.0 if there is no hit.

    Deliberately NOT truncated to a `k` — MRR is conventionally computed over
    the full ranking; `runner.py` passes the whole retrieved list here even
    though it caps the other metrics at `k`.
    """
    rel = _relevant_set(relevant)
    retrieved = _dedupe(retrieved)
    if not rel or not retrieved:
        return 0.0
    for rank, doc in enumerate(retrieved, start=1):
        if doc in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Normalized DCG over the top-`k`, binary relevance, standard log2 discount.

    Formula:
        DCG  = sum(1 / log2(rank + 1)) over relevant docs in `retrieved[:k]`,
               `rank` 1-indexed.
        IDCG = DCG of the *ideal* ranking — the `min(k, |relevant|)` relevant
               docs packed at the top.
        nDCG = DCG / IDCG.

    IDCG is 0 exactly when there is nothing relevant to rank (`relevant` is
    empty) or when `k <= 0` — both resolve to nDCG = 0.0 instead of a
    ZeroDivisionError.
    """
    rel = _relevant_set(relevant)
    retrieved = _dedupe(retrieved)
    if not rel or not retrieved or k <= 0:
        return 0.0

    top = retrieved[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1) for rank, doc in enumerate(top, start=1) if doc in rel
    )
    ideal_hits = min(k, len(rel))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def context_precision(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the top-`k` retrieved docs that are actually relevant.

    Formula: ``|retrieved[:k] ∩ relevant| / |retrieved[:k]|``.

    0.0 when nothing was retrieved — an empty result answered nothing, which
    is not the same as answering perfectly, so this is NOT vacuously 1.0.
    """
    rel = _relevant_set(relevant)
    retrieved = _dedupe(retrieved)
    top = retrieved[:k] if k > 0 else []
    if not top:
        return 0.0
    return sum(1 for doc in top if doc in rel) / len(top)


def context_recall(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the relevant set that appears anywhere in the top-`k`.

    Formula: ``|retrieved[:k] ∩ relevant| / |relevant|``.

    0.0 when `relevant` is empty. This mirrors `hit_rate`'s convention rather
    than the vacuous-truth alternative (1.0): the golden set's two
    deliberately unanswerable questions have no relevant document by design,
    and a harness that scored those as "perfect recall" would hide exactly
    the confabulation failure mode it exists to catch.
    """
    rel = _relevant_set(relevant)
    retrieved = _dedupe(retrieved)
    if not rel:
        return 0.0
    top = retrieved[:k] if k > 0 else []
    found = sum(1 for doc in rel if doc in top)
    return found / len(rel)
