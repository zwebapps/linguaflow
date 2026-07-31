"""Turns text into vectors — `contracts.Embedder` implementations + a singleton factory.

OpenRouter is the default (no local model download); a local `sentence-transformers`
path exists for fully-offline dev but is deliberately NOT a hard dependency — it
pulls in torch (~2 GB), so it's only imported when someone actually asks for it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.ai import embeddings as ai_embeddings
from app.core.config import settings
from app.core.errors import UpstreamError

log = structlog.get_logger(__name__)

# Multilingual, small, and covers German well — a sane default if someone flips to
# EMBEDDING_BACKEND=local without picking a model explicitly.
_DEFAULT_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class OpenRouterEmbedder:
    """Delegates to `app.ai.embeddings` — no HTTP lives here.

    The AI track already owns batching, retries and the dimension assertion
    (see `_assert_dim` in embeddings.py); this class is just the
    `contracts.Embedder`-shaped adapter over it.
    """

    def __init__(self, *, model: str | None = None, dim: int | None = None) -> None:
        self.model = model or settings.EMBEDDING_MODEL
        self.dim = dim or settings.EMBEDDING_DIM

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = await ai_embeddings.embed_texts(texts, model=self.model)
        return result.vectors

    async def embed_query(self, text: str) -> list[float]:
        return await ai_embeddings.embed_query(text, model=self.model)


class LocalEmbedder:
    """Offline dev path. Not installed by default — see `local-embeddings` extra.

    The model load is lazy (constructor does no import, no download) so simply
    selecting EMBEDDING_BACKEND=local in settings never breaks a machine that
    isn't running local embeddings; the failure only happens the first time this
    embedder is actually asked to encode something.
    """

    def __init__(self, *, model_name: str | None = None) -> None:
        self.model_name = model_name or _DEFAULT_LOCAL_MODEL
        self.dim = settings.EMBEDDING_DIM
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:  # re-check: another task may have won the race
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise UpstreamError(
                    "EMBEDDING_BACKEND=local but sentence-transformers isn't installed. "
                    'Run `pip install -e ".[local-embeddings]"` to enable it, or switch '
                    "EMBEDDING_BACKEND back to openrouter."
                ) from exc

            # Model download/load is blocking and can take seconds — off the event loop.
            model = await asyncio.to_thread(SentenceTransformer, self.model_name)
            actual_dim = model.get_sentence_embedding_dimension()
            if actual_dim and actual_dim != self.dim:
                # Same failure mode as the OpenRouter path's `_assert_dim` — better to
                # log and self-correct than to silently poison the vector collection.
                log.warning(
                    "local_embedder_dim_mismatch",
                    model=self.model_name,
                    expected=self.dim,
                    actual=actual_dim,
                )
                self.dim = actual_dim
            self._model = model
            return model

    async def _encode(self, texts: list[str]) -> list[list[float]]:
        model = await self._get_model()
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._encode(texts)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._encode([text])
        return vectors[0] if vectors else []


_embedder: OpenRouterEmbedder | LocalEmbedder | None = None


def get_embedder() -> OpenRouterEmbedder | LocalEmbedder:
    """Process-wide singleton, chosen by `settings.EMBEDDING_BACKEND`.

    A singleton matters more for `LocalEmbedder` (avoids reloading the model per
    request) but is harmless and consistent for `OpenRouterEmbedder` too.
    """
    global _embedder
    if _embedder is None:
        if settings.EMBEDDING_BACKEND == "local":
            _embedder = LocalEmbedder()
        else:
            _embedder = OpenRouterEmbedder()
    return _embedder
