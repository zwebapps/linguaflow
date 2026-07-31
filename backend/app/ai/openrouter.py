"""OpenRouter integration — the single egress for every LLM call.

We use LangChain's ``ChatOpenAI`` pointed at OpenRouter's OpenAI-compatible endpoint
(the mandated stack). Because it is OpenAI-compatible, switching models is literally
swapping the ``model`` string — which is what makes multi-model support intrinsic
rather than bolted on.

This module also owns the model *catalog* (for the admin picker) and cost maths.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.errors import UpstreamError

log = structlog.get_logger(__name__)

_CATALOG_URL = "https://openrouter.ai/api/v1/models"
_catalog_cache: dict[str, Any] = {"at": 0.0, "models": []}
_CATALOG_TTL = 60 * 30


def _headers() -> dict[str, str]:
    # OpenRouter asks for these two for attribution / rankings.
    return {
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_TITLE,
    }


def make_llm(model: str, *, streaming: bool = False, **params: Any) -> ChatOpenAI:
    """Build a LangChain chat model bound to OpenRouter.

    `model` is an OpenRouter slug, e.g. "anthropic/claude-3.7-sonnet".
    """
    if not settings.OPENROUTER_API_KEY:
        raise UpstreamError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env to enable AI features."
        )

    allowed = {"temperature", "max_tokens", "top_p", "presence_penalty", "frequency_penalty"}
    kwargs = {k: v for k, v in params.items() if k in allowed and v is not None}

    return ChatOpenAI(
        model=model,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        streaming=streaming,
        # Without this, a STREAMED response carries no usage_metadata at all and
        # every token/cost figure silently reads zero — which would quietly break
        # the cost dashboard and quota enforcement.
        stream_usage=True,
        timeout=90,
        max_retries=0,  # the AI Router owns retries/fallbacks, not the SDK
        default_headers=_headers(),
        **kwargs,
    )


async def fetch_catalog(force: bool = False) -> list[dict[str, Any]]:
    """Model catalog for the admin model-picker, cached for 30 min."""
    now = time.time()
    if not force and _catalog_cache["models"] and now - _catalog_cache["at"] < _CATALOG_TTL:
        return _catalog_cache["models"]  # type: ignore[return-value]

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(_CATALOG_URL, headers=_headers())
            res.raise_for_status()
            raw = res.json().get("data", [])
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("openrouter_catalog_failed", error=str(exc))
        if _catalog_cache["models"]:
            return _catalog_cache["models"]  # type: ignore[return-value]
        raise UpstreamError("Couldn't load the model catalog from OpenRouter.") from exc

    models = []
    for m in raw:
        pricing = m.get("pricing") or {}
        params = m.get("supported_parameters") or []
        models.append(
            {
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "context_length": m.get("context_length"),
                # OpenRouter prices are USD per token; present per 1k for humans.
                "prompt_usd_per_1k": _f(pricing.get("prompt")) * 1000,
                "completion_usd_per_1k": _f(pricing.get("completion")) * 1000,
                "supports_tools": "tools" in params or "tool_choice" in params,
            }
        )

    models.sort(key=lambda m: m["id"] or "")
    _catalog_cache.update({"at": now, "models": models})
    return models


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def price_for(model: str) -> tuple[float, float]:
    """(prompt_usd_per_token, completion_usd_per_token) — 0.0 if unknown."""
    try:
        for m in await fetch_catalog():
            if m["id"] == model:
                return (
                    m["prompt_usd_per_1k"] / 1000,
                    m["completion_usd_per_1k"] / 1000,
                )
    except UpstreamError:
        pass
    return (0.0, 0.0)


async def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> tuple[float, int]:
    """→ (cost_usd, cost_micro_usd)."""
    p_in, p_out = await price_for(model)
    usd = tokens_in * p_in + tokens_out * p_out
    return round(usd, 6), int(round(usd * 1_000_000))


def supports_tools_hint(model: str) -> bool:
    """Best-effort sync check from the warm cache; assume True when unknown."""
    for m in _catalog_cache.get("models") or []:
        if m["id"] == model:
            return bool(m["supports_tools"])
    return True
