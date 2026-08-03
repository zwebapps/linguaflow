"""The real `retrieve()` — dense vector search, optionally fused with BM25 keyword
search over the same candidate pool via Reciprocal Rank Fusion (RRF).

Signature is FROZEN (see `app/rag/contracts.py`). Never raises for "no results" —
a tool-calling tutor asking a question nobody has written material for is normal
traffic, not an error; both search halves are individually best-effort so a
degraded vector store or a slow DB thins the answer instead of breaking it.
"""

from __future__ import annotations

import re
import time

import structlog
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Chunk, Document
from app.rag.contracts import DEFAULT_COLLECTION, RetrievedChunk, SearchResult
from app.rag.embedder import get_embedder
from app.rag.vector_store import get_vector_store

log = structlog.get_logger(__name__)

# Standard RRF damping constant (the value used in the original Cormack et al.
# paper and in most hybrid-search writeups) — large enough that a #1 rank in one
# list doesn't completely drown out a #2-#3 rank in the other.
_RRF_K = 60

# BM25 needs its whole candidate pool in memory to score. Capping it keeps a
# large collection from turning every query into a full client-side table scan.
_BM25_CANDIDATE_POOL = 500

_SNIPPET_LEN = 240
_TOKEN_RE = re.compile(r"[a-zA-ZäöüÄÖÜßA-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


async def retrieve(
    db: AsyncSession,
    query: str,
    *,
    cefr_level: str | None = None,
    skill: str | None = None,
    k: int | None = None,
    strategy: str | None = None,
    document_id: str | None = None,
    collection: str | None = None,
    # The language of the material to ground in. None keeps the pre-multilingual
    # behaviour (search everything) so internal callers that have no learner
    # context — evals, admin reindex — are unaffected.
    language: str | None = None,
) -> SearchResult:
    started = time.perf_counter()
    strategy = strategy or settings.SEARCH_STRATEGY
    top_k = k or settings.RETRIEVAL_TOP_K
    collection = collection or DEFAULT_COLLECTION

    if not query or not query.strip():
        return SearchResult(query=query, strategy=strategy, results=[], took_ms=0)

    try:
        dense_hits = await _dense_search(
            db,
            query,
            collection=collection,
            cefr_level=cefr_level,
            skill=skill,
            document_id=document_id,
            language=language,
            k=top_k,
        )
    except Exception as exc:
        log.warning("retrieve_dense_failed", error=str(exc), collection=collection)
        dense_hits = []

    if strategy == "dense":
        results = dense_hits[:top_k]
    elif strategy == "keyword":
        # BM25 alone — the third arm of the classic retrieval ablation
        # (dense vs keyword vs fusion). The dense pool above is simply unused;
        # skipping the embed call entirely would need restructuring the happy
        # path for an experiment arm, which is not worth it.
        try:
            results = await _keyword_search(
                db,
                query,
                collection=collection,
                cefr_level=cefr_level,
                skill=skill,
                document_id=document_id,
                language=language,
                k=top_k,
            )
        except Exception as exc:
            log.warning("retrieve_keyword_failed", error=str(exc), collection=collection)
            results = []
    else:
        try:
            keyword_hits = await _keyword_search(
                db,
                query,
                collection=collection,
                cefr_level=cefr_level,
                skill=skill,
                document_id=document_id,
                language=language,
                k=top_k,
            )
        except Exception as exc:
            log.warning("retrieve_keyword_failed", error=str(exc), collection=collection)
            keyword_hits = []
        results = _fuse(dense_hits, keyword_hits, k=top_k)
        strategy = "hybrid"

    for r in results:
        r.snippet = _make_snippet(r.text, query)

    took_ms = int((time.perf_counter() - started) * 1000)
    return SearchResult(query=query, strategy=strategy, results=results, took_ms=took_ms)


# ── Dense half ────────────────────────────────────────────────────────────────


async def _dense_search(
    db: AsyncSession,
    query: str,
    *,
    collection: str,
    cefr_level: str | None,
    skill: str | None,
    document_id: str | None,
    language: str | None,
    k: int,
) -> list[RetrievedChunk]:
    vector = await get_embedder().embed_query(query)
    if not vector:
        return []

    # `contracts.VectorStore.search` has no `document_id` or `language` filter —
    # pull a wider pool and post-filter here rather than widen the frozen
    # interface for one caller's need.
    #
    # Language would ideally be a per-language COLLECTION (`kb_de`, `kb_es`):
    # the index would then hold one language, which both removes this
    # post-filter and stops cross-language neighbours competing for the top-k.
    # That is an ingestion-side change and a bigger move than this one; the
    # post-filter is exact in the meantime.
    narrowing = document_id or language
    pool = max(k * 5, 50) if narrowing else k
    store = get_vector_store()
    hits = await store.search(collection, vector, k=pool, cefr_level=cefr_level, skill=skill)
    if document_id:
        hits = [h for h in hits if h.document_id == str(document_id)]
    if language and hits:
        hits = await _keep_language(db, hits, language)
    return hits[:k]


async def _keep_language(
    db: AsyncSession, hits: list[RetrievedChunk], language: str
) -> list[RetrievedChunk]:
    """Drop hits whose document is in another language.

    One query over the ids already retrieved, not one per hit — the pool is
    bounded by `k * 5`, so this stays a single round-trip regardless of corpus
    size. Order is preserved: the vector store ranked these, and re-sorting here
    would silently discard that ranking.
    """
    ids = {h.document_id for h in hits if h.document_id}
    if not ids:
        return hits
    rows = await db.execute(
        select(Document.id).where(Document.id.in_(ids), Document.language == language)
    )
    keep = {str(r[0]) for r in rows}
    return [h for h in hits if h.document_id in keep]


# ── Keyword half ──────────────────────────────────────────────────────────────


async def _keyword_search(
    db: AsyncSession,
    query: str,
    *,
    collection: str,
    cefr_level: str | None,
    skill: str | None,
    document_id: str | None,
    language: str | None,
    k: int,
) -> list[RetrievedChunk]:
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.collection == collection)
    )
    if language:
        stmt = stmt.where(Document.language == language)
    if cefr_level:
        stmt = stmt.where(Chunk.cefr_level == cefr_level)
    if skill:
        stmt = stmt.where(Chunk.skill == skill)
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
    # ORDER BY is required, not cosmetic: without it Postgres returns an arbitrary
    # slice once a collection exceeds the pool size, so the keyword half scored a
    # nondeterministic subset and the same query could give different answers run
    # to run. Newest-first at least makes the truncation defined and repeatable.
    stmt = stmt.order_by(Chunk.created_at.desc(), Chunk.id).limit(_BM25_CANDIDATE_POOL)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    corpus = [_tokenize(chunk.text) for chunk, _title in rows]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(zip(rows, scores, strict=True), key=lambda item: item[1], reverse=True)

    results: list[RetrievedChunk] = []
    for (chunk, title), score in ranked[:k]:
        if score <= 0:
            continue  # BM25 "matched nothing" — don't dress it up as a hit
        results.append(
            RetrievedChunk(
                id=str(chunk.id),
                document_id=str(chunk.document_id),
                title=title or "",
                text=chunk.text,
                snippet=chunk.text[:_SNIPPET_LEN],
                score=float(score),
                keyword_score=float(score),
                page=chunk.page,
                cefr_level=chunk.cefr_level,
            )
        )
    return results


# ── Fusion ────────────────────────────────────────────────────────────────────


def _fuse(
    dense: list[RetrievedChunk], keyword: list[RetrievedChunk], *, k: int
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion: score(doc) = sum(1 / (RRF_K + rank_in_list)).

    Rank-based (not raw-score-based) on purpose — dense cosine similarities and
    BM25 scores live on unrelated scales, so combining them by rank is what
    makes "found by both" reliably outrank "found by only one".
    """
    if not dense and not keyword:
        return []
    if not keyword:
        return dense[:k]
    if not dense:
        return keyword[:k]

    merged: dict[str, RetrievedChunk] = {}
    fused: dict[str, float] = {}

    for rank, chunk in enumerate(dense, start=1):
        merged[chunk.id] = chunk
        fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)

    for rank, chunk in enumerate(keyword, start=1):
        existing = merged.get(chunk.id)
        if existing is not None:
            existing.keyword_score = chunk.keyword_score
        else:
            merged[chunk.id] = chunk
        fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)

    ordered = sorted(merged.values(), key=lambda c: fused[c.id], reverse=True)
    for c in ordered:
        c.score = fused[c.id]
    return ordered[:k]


# ── Snippet ───────────────────────────────────────────────────────────────────


def _make_snippet(text: str, query: str) -> str:
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""

    lower = normalized.lower()
    pos = -1
    for term in _tokenize(query):
        if len(term) <= 2:  # skip stopword-ish noise (articles, prepositions)
            continue
        pos = lower.find(term)
        if pos != -1:
            break

    if pos == -1:
        head = normalized[:_SNIPPET_LEN]
        return head + ("…" if len(normalized) > _SNIPPET_LEN else "")

    half = _SNIPPET_LEN // 2
    start = max(0, pos - half)
    end = min(len(normalized), start + _SNIPPET_LEN)
    start = max(0, end - _SNIPPET_LEN)  # re-pull start left if we hit the tail
    excerpt = normalized[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{excerpt}{suffix}"
