"""`contracts.VectorStore` implementations — Qdrant (primary) and pgvector (fallback).

Selected once, at process start, by `settings.VECTOR_BACKEND`; `get_vector_store()`
is the process-wide singleton every other module (including `/readyz`) should call
instead of constructing a store directly.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm
from sqlalchemy import select
from sqlalchemy import update as sa_update

from app.core.config import settings
from app.core.errors import UpstreamError
from app.db.models import Chunk, Document
from app.rag.contracts import RetrievedChunk

log = structlog.get_logger(__name__)


def _snippet(text: str, limit: int = 240) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


# ── Qdrant ────────────────────────────────────────────────────────────────────


class QdrantStore:
    """Primary backend. One Qdrant collection per RAG `collection` name, cosine
    distance, `EMBEDDING_DIM`-sized vectors."""

    def __init__(self) -> None:
        self._client: AsyncQdrantClient | None = None
        self._ensured: set[str] = set()

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=30,
            )
        return self._client

    async def ensure_collection(self, collection: str) -> None:
        # Cheap in-process memo so a hot search path doesn't round-trip to Qdrant
        # to ask "does this collection exist" on every single query.
        if collection in self._ensured:
            return
        client = self._get_client()
        try:
            if not await client.collection_exists(collection):
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=qm.VectorParams(
                        size=settings.EMBEDDING_DIM, distance=qm.Distance.COSINE
                    ),
                )
                # Indexes make the cefr_level/skill/document_id filters in
                # search()/delete_by_document() sublinear instead of a full scan
                # once a collection has real volume behind it.
                for field_name in ("cefr_level", "skill", "document_id"):
                    await client.create_payload_index(
                        collection_name=collection,
                        field_name=field_name,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
        except Exception as exc:
            raise UpstreamError(
                f"Could not prepare Qdrant collection '{collection}': {exc}"
            ) from exc
        self._ensured.add(collection)

    async def upsert(self, collection: str, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        await self.ensure_collection(collection)
        client = self._get_client()

        points = [
            qm.PointStruct(
                id=str(c["id"]),
                vector=c["vector"],
                payload={
                    "chunk_id": str(c["id"]),
                    "document_id": str(c.get("document_id") or ""),
                    "title": c.get("title") or "",
                    "text": c.get("text") or "",
                    "page": c.get("page"),
                    "cefr_level": c.get("cefr_level"),
                    "skill": c.get("skill"),
                },
            )
            for c in chunks
        ]
        try:
            await client.upsert(collection_name=collection, points=points)
        except Exception as exc:
            raise UpstreamError(f"Qdrant upsert failed for '{collection}': {exc}") from exc

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        k: int = 6,
        cefr_level: str | None = None,
        skill: str | None = None,
    ) -> list[RetrievedChunk]:
        await self.ensure_collection(collection)
        client = self._get_client()

        must: list[Any] = []
        if cefr_level:
            must.append(qm.FieldCondition(key="cefr_level", match=qm.MatchValue(value=cefr_level)))
        if skill:
            must.append(qm.FieldCondition(key="skill", match=qm.MatchValue(value=skill)))
        query_filter = qm.Filter(must=must) if must else None

        try:
            response = await client.query_points(
                collection_name=collection,
                query=vector,
                limit=k,
                query_filter=query_filter,
                with_payload=True,
            )
        except Exception as exc:
            raise UpstreamError(f"Qdrant search failed for '{collection}': {exc}") from exc

        results: list[RetrievedChunk] = []
        for point in response.points:
            payload = point.payload or {}
            text = str(payload.get("text") or "")
            results.append(
                RetrievedChunk(
                    id=str(payload.get("chunk_id") or point.id),
                    document_id=str(payload.get("document_id") or ""),
                    title=str(payload.get("title") or ""),
                    text=text,
                    snippet=_snippet(text),
                    score=float(point.score),
                    dense_score=float(point.score),
                    page=payload.get("page"),
                    cefr_level=payload.get("cefr_level"),
                )
            )
        return results

    async def delete_by_document(self, collection: str, document_id: str) -> None:
        client = self._get_client()
        try:
            if not await client.collection_exists(collection):
                return  # nothing to delete from a collection that was never created
            await client.delete(
                collection_name=collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[
                            qm.FieldCondition(
                                key="document_id", match=qm.MatchValue(value=str(document_id))
                            )
                        ]
                    )
                ),
            )
        except Exception as exc:
            raise UpstreamError(f"Qdrant delete failed for '{collection}': {exc}") from exc

    async def health(self) -> bool:
        try:
            await self._get_client().get_collections()
            return True
        except Exception as exc:
            log.warning("qdrant_health_failed", error=str(exc))
            return False


# ── pgvector ──────────────────────────────────────────────────────────────────


class PgVectorStore:
    """Fallback backend — cosine ordering on the `chunks.embedding` column.

    Chunk *rows* (text, heading, page, ordinal) are created by the ingestion
    service, not here; this store only ever reads/writes the `embedding` column
    and runs the similarity query, so it is genuinely just an alternate index
    over data Postgres already owns — no separate collection to keep in sync.
    """

    async def ensure_collection(self, collection: str) -> None:
        # No-op: the `chunks` table + pgvector column exist via Alembic
        # migrations. `collection` still narrows queries via `documents.collection`.
        return

    async def upsert(self, collection: str, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        from app.db.session import SessionLocal

        async with SessionLocal() as db:
            for c in chunks:
                await db.execute(
                    sa_update(Chunk)
                    .where(Chunk.id == uuid.UUID(str(c["id"])))
                    .values(embedding=c["vector"])
                )
            await db.commit()

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        k: int = 6,
        cefr_level: str | None = None,
        skill: str | None = None,
    ) -> list[RetrievedChunk]:
        from app.db.session import SessionLocal

        distance = Chunk.embedding.cosine_distance(vector)
        stmt = (
            select(Chunk, Document.title, distance.label("distance"))
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.collection == collection, Chunk.embedding.is_not(None))
        )
        if cefr_level:
            stmt = stmt.where(Chunk.cefr_level == cefr_level)
        if skill:
            stmt = stmt.where(Chunk.skill == skill)
        stmt = stmt.order_by(distance).limit(k)

        async with SessionLocal() as db:
            try:
                rows = (await db.execute(stmt)).all()
            except Exception as exc:
                raise UpstreamError(f"pgvector search failed for '{collection}': {exc}") from exc

        results: list[RetrievedChunk] = []
        for chunk, title, dist in rows:
            similarity = 1.0 - float(dist)  # cosine_distance -> similarity
            results.append(
                RetrievedChunk(
                    id=str(chunk.id),
                    document_id=str(chunk.document_id),
                    title=title or "",
                    text=chunk.text,
                    snippet=_snippet(chunk.text),
                    score=similarity,
                    dense_score=similarity,
                    page=chunk.page,
                    cefr_level=chunk.cefr_level,
                )
            )
        return results

    async def delete_by_document(self, collection: str, document_id: str) -> None:
        from app.db.session import SessionLocal

        async with SessionLocal() as db:
            # Clears the vector rather than deleting the row: row lifecycle
            # (cascade on Document delete) belongs to the ingestion service, not
            # the vector-store seam. A cleared embedding simply stops matching.
            await db.execute(
                sa_update(Chunk)
                .where(Chunk.document_id == uuid.UUID(str(document_id)))
                .values(embedding=None)
            )
            await db.commit()

    async def health(self) -> bool:
        from app.db.session import SessionLocal

        try:
            async with SessionLocal() as db:
                await db.execute(select(1))
            return True
        except Exception as exc:
            log.warning("pgvector_health_failed", error=str(exc))
            return False


_store: QdrantStore | PgVectorStore | None = None


def get_vector_store() -> QdrantStore | PgVectorStore:
    global _store
    if _store is None:
        _store = PgVectorStore() if settings.VECTOR_BACKEND == "pgvector" else QdrantStore()
    return _store
