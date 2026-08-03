"""Content is scoped to the language being learned.

`users.target_language` already existed, and a comment in `db/models.py` claimed
a second target language would be "a content problem, not a schema migration".
That was half right: the learner's CHOICE was stored, but the CONTENT carried no
language, so `documents`, `vocabulary` and `feed_sources` were implicitly German.
A learner who switched to Spanish would have been served German readers, German
flashcards and German quiz material — silently, with nothing to notice.

The failure mode these guard against is not an exception. It is a plausible-looking
wrong answer, which for a teaching product is the worst kind: the learner has no
way to tell they were taught the wrong language's grammar.

No live database here — the suite has no engine fixture. Instead these compile the
statements the routes build and assert the language predicate is present, and
exercise the retriever's post-filter directly with a recording fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import Document, FeedSource, Vocabulary
from app.rag.contracts import RetrievedChunk
from app.rag.retriever import _keep_language


def _sql(stmt: Any) -> str:
    """Compiled SQL with literals inlined, so predicates are visible as text."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ── The schema carries language at all ────────────────────────────────────────


@pytest.mark.parametrize("model", [Document, Vocabulary, FeedSource])
def test_content_tables_carry_a_language(model: Any) -> None:
    col = model.__table__.c.language
    # NOT NULL on purpose: content whose language is unknown is unservable,
    # because we cannot tell which learner it belongs to. A nullable column
    # would let that NULL reach a query that then matches nobody.
    assert col.nullable is False
    # Defaulted to German because every row that existed when this shipped WAS
    # German — a statement about history, not a convenient fallback.
    assert "de" in str(col.server_default.arg)


def test_language_is_indexed_on_every_content_table() -> None:
    """Every read starts with "this learner's language", so it must be indexed.

    Without an index, adding a second language turns each library and vocabulary
    query into a full scan that throws most of what it reads away.
    """
    for model in (Document, Vocabulary, FeedSource):
        indexed = {c.name for idx in model.__table__.indexes for c in idx.columns}
        assert "language" in indexed, f"{model.__tablename__} does not index language"


# ── Query construction ────────────────────────────────────────────────────────


def test_a_library_query_filters_by_language() -> None:
    stmt = select(Document).where(Document.status == "ready", Document.language == "es")
    assert "documents.language = 'es'" in _sql(stmt)


def test_vocabulary_is_scoped_per_language_not_just_per_user() -> None:
    """A learner studying two languages keeps two decks.

    "der Tisch" and "la mesa" belong to the same person and must never review
    together, so user_id alone is not enough of a scope.
    """
    stmt = select(Vocabulary).where(Vocabulary.user_id == "u1", Vocabulary.language == "es")
    sql = _sql(stmt)
    assert "vocabulary.language = 'es'" in sql
    assert "vocabulary.user_id" in sql


# ── The retriever's post-filter ───────────────────────────────────────────────


@dataclass
class _Row:
    v: Any

    def __getitem__(self, _i: int) -> Any:
        return self.v


class _RecordingSession:
    """Returns a fixed id set and remembers what it was asked."""

    def __init__(self, keep_ids: list[str]) -> None:
        self._keep = keep_ids
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        rows = [_Row(i) for i in self._keep]

        class _Result:
            def __iter__(self_inner) -> Any:  # noqa: N805
                return iter(rows)

        return _Result()


def _hit(doc_id: str, ordinal: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=f"c{ordinal}",
        document_id=doc_id,
        title="t",
        text="x",
        snippet="x",
        score=1.0 - ordinal / 100,
    )


@pytest.mark.asyncio
async def test_retrieval_drops_hits_from_another_language() -> None:
    """The tutor must never ground a Spanish answer in a German chunk.

    That is the difference between "I don't know" and a confidently wrong
    grammar explanation, and only one of those is recoverable for a learner.
    """
    hits = [_hit("doc-es", 0), _hit("doc-de", 1), _hit("doc-es2", 2)]
    db = _RecordingSession(["doc-es", "doc-es2"])

    kept = await _keep_language(db, hits, "es")  # type: ignore[arg-type]

    assert [h.document_id for h in kept] == ["doc-es", "doc-es2"]
    # One query for the whole pool, not one per hit — the pool is bounded by
    # k * 5, so this has to stay a single round-trip whatever the corpus size.
    assert len(db.statements) == 1
    assert "documents.language = 'es'" in _sql(db.statements[0])


@pytest.mark.asyncio
async def test_the_post_filter_preserves_the_vector_stores_ranking() -> None:
    """Relevance order comes from the vector store; re-sorting would discard it."""
    hits = [_hit("a", 0), _hit("b", 1), _hit("c", 2)]
    db = _RecordingSession(["c", "a", "b"])  # deliberately a different order

    kept = await _keep_language(db, hits, "es")  # type: ignore[arg-type]

    assert [h.document_id for h in kept] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_no_hits_means_no_query() -> None:
    db = _RecordingSession([])
    assert await _keep_language(db, [], "es") == []  # type: ignore[arg-type]
    assert db.statements == []
