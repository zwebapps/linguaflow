"""Embeddings via OpenRouter's dedicated `/embeddings` endpoint.

OpenRouter is OpenAI-schema compatible here, so the same key that serves chat also
serves embeddings — one egress, one bill, and the model stays swappable from the
admin UI like every other task.

`POST /api/v1/embeddings  {model, input: str | str[], dimensions?, encoding_format?}`
  → `{data: [{embedding: number[], index}], model, usage: {prompt_tokens, total_tokens}}`

A local `sentence-transformers` path stays available for offline dev behind the same
`Embedder` protocol (see `app/rag/embedder.py`).
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.errors import UpstreamError

log = structlog.get_logger(__name__)

# Batch size for document embedding. Keeps request bodies well under limits while
# still amortising round-trips over a whole document's chunks.
BATCH_SIZE = 64


def _headers() -> dict[str, str]:
    if not settings.OPENROUTER_API_KEY:
        raise UpstreamError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env to enable embeddings."
        )
    return {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_TITLE,
    }


class EmbeddingResult:
    __slots__ = ("vectors", "model", "tokens")

    def __init__(self, vectors: list[list[float]], model: str, tokens: int) -> None:
        self.vectors = vectors
        self.model = model
        self.tokens = tokens


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _post_embeddings(texts: list[str], model: str, dimensions: int | None) -> dict:
    payload: dict = {"model": model, "input": texts, "encoding_format": "float"}
    # Only send `dimensions` when the caller wants to shrink the native size —
    # not every model accepts the parameter.
    if dimensions:
        payload["dimensions"] = dimensions

    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/embeddings",
            headers=_headers(),
            json=payload,
        )
        # 4xx other than 429 is our bug (bad model/params) — don't burn retries on it.
        if res.status_code == 429 or res.status_code >= 500:
            res.raise_for_status()
        if res.status_code >= 400:
            raise UpstreamError(
                f"Embedding request rejected ({res.status_code}): {res.text[:200]}"
            )
        return res.json()


async def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
) -> EmbeddingResult:
    """Embed a batch of texts, preserving input order."""
    if not texts:
        return EmbeddingResult([], model or settings.EMBEDDING_MODEL, 0)

    model = model or settings.EMBEDDING_MODEL
    # `dimensions` defaults to None (native size); EMBEDDING_DIM is what we *expect*
    # and is asserted below rather than blindly requested.
    vectors: list[list[float]] = []
    total_tokens = 0
    used_model = model

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        try:
            data = await _post_embeddings(batch, model, dimensions)
        except UpstreamError:
            raise
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"Embedding provider returned {exc.response.status_code}. Please retry."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Couldn't reach the embedding provider: {exc}") from exc

        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        if len(rows) != len(batch):
            raise UpstreamError(
                f"Embedding provider returned {len(rows)} vectors for {len(batch)} inputs."
            )
        vectors.extend([r["embedding"] for r in rows])
        used_model = data.get("model") or model
        total_tokens += int((data.get("usage") or {}).get("total_tokens", 0) or 0)

        # Be polite between batches on large documents.
        if start + BATCH_SIZE < len(texts):
            await asyncio.sleep(0.05)

    _assert_dim(vectors)
    return EmbeddingResult(vectors, used_model, total_tokens)


async def embed_query(text: str, *, model: str | None = None) -> list[float]:
    result = await embed_texts([text], model=model)
    return result.vectors[0] if result.vectors else []


def _assert_dim(vectors: list[list[float]]) -> None:
    """Fail fast on a dimension mismatch.

    A wrong EMBEDDING_DIM silently poisons the vector collection — every upsert is
    rejected or, worse, the collection is created at the wrong size. Catching it at
    the first embed call with a clear message beats debugging Qdrant errors later.
    """
    if not vectors:
        return
    actual = len(vectors[0])
    if actual != settings.EMBEDDING_DIM:
        raise UpstreamError(
            f"Embedding dimension mismatch: model '{settings.EMBEDDING_MODEL}' returned "
            f"{actual} dims but EMBEDDING_DIM={settings.EMBEDDING_DIM}. "
            f"Set EMBEDDING_DIM={actual} in .env (and recreate the vector collection)."
        )
