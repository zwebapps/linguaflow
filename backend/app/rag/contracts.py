"""The RAG boundary — the ONE interface shared across backend tracks.

* The **RAG track** implements these (parsers, embedder, vector stores, retriever).
* The **agent/API track** only ever consumes ``retrieve()`` and these dataclasses.

Changing anything here means changing both sides, so treat it as frozen unless
there's a real reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class RetrievedChunk:
    """One retrieved passage, ready to cite in the API response."""

    id: str
    document_id: str
    title: str
    text: str                       # full chunk text (for prompting)
    snippet: str                    # short display excerpt (for the UI)
    score: float                    # fused/final relevance score
    dense_score: float | None = None
    keyword_score: float | None = None
    page: int | None = None
    url: str | None = None
    cefr_level: str | None = None

    def as_source(self) -> dict[str, Any]:
        """The shape the frontend expects in an SSE `sources` event / `sources[]` field."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "title": self.title,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "page": self.page,
            "url": self.url,
        }


@dataclass(slots=True)
class SearchResult:
    query: str
    strategy: str                   # "hybrid" | "dense"
    results: list[RetrievedChunk] = field(default_factory=list)
    took_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "results": [
                {**asdict(c), "score": round(c.score, 4)} for c in self.results
            ],
            "took_ms": self.took_ms,
        }


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. Local model by default; hosted is a config flip."""

    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStore(Protocol):
    """Qdrant or pgvector — chosen by ``settings.VECTOR_BACKEND``."""

    async def ensure_collection(self, collection: str) -> None: ...

    async def upsert(
        self, collection: str, chunks: list[dict[str, Any]]
    ) -> None:
        """`chunks` items: {id, vector, document_id, text, title, page, cefr_level, skill}."""
        ...

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        k: int = 6,
        cefr_level: str | None = None,
        skill: str | None = None,
    ) -> list[RetrievedChunk]: ...

    async def delete_by_document(self, collection: str, document_id: str) -> None: ...

    async def health(self) -> bool: ...


# ── The single function the agent/API track calls ────────────────────────────
#
# Implemented in `app/rag/retriever.py` with EXACTLY this signature:
#
#   async def retrieve(
#       db: AsyncSession,
#       query: str,
#       *,
#       cefr_level: str | None = None,
#       skill: str | None = None,
#       k: int | None = None,
#       strategy: str | None = None,      # None → settings.SEARCH_STRATEGY
#       document_id: str | None = None,   # restrict to one document
#       collection: str | None = None,
#   ) -> SearchResult
#
# It must never raise for "no results" — an empty `results` list is a valid answer.

DEFAULT_COLLECTION = "grammar_documents"

COLLECTIONS = (
    "grammar_documents",
    "stories",
    "lesson_content",
    "vocabulary_examples",
    "user_notes",
)
