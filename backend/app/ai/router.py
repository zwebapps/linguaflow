"""The AI Router — task → model, with fallbacks, caching and usage accounting.

This is the piece that makes the app model-agnostic (ARCHITECTURE.md §5.3):

    route(task) → policy from DB → try primary → on failure try each fallback
                → record tokens/cost/latency → optionally cache deterministic results

Callers never name a model. They name a *task*.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import AIMessage, BaseMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openrouter import estimate_cost, make_llm
from app.ai.tasks import NON_CHAT_TASKS, RoutePolicy, TaskType
from app.core.errors import AllModelsFailed, UpstreamError
from app.db.models import AIRoute, AIUsage

log = structlog.get_logger(__name__)


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class AIResult:
    text: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cost_micro_usd: int = 0
    latency_ms: int = 0
    from_cache: bool = False
    fallback_used: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def usage_dict(self) -> dict[str, Any]:
        return {
            "model": self.model_used,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "from_cache": self.from_cache,
            "latency_ms": self.latency_ms,
        }


# ── Policy resolution ─────────────────────────────────────────────────────────


async def load_policy(db: AsyncSession, task_type: str) -> RoutePolicy:
    """DB policy if an admin has customised it, else the seeded default."""
    row = await db.get(AIRoute, str(task_type))
    if row is None:
        return RoutePolicy.default_for(str(task_type))

    default = RoutePolicy.default_for(str(task_type))
    return RoutePolicy(
        task_type=row.task_type,
        primary_model=row.primary_model,
        fallbacks=list(row.fallbacks or []),
        params=dict(row.params or {}),
        cacheable=default.cacheable,
        cache_ttl=default.cache_ttl,
    )


async def seed_routes(db: AsyncSession) -> int:
    """Insert any missing default routes. Idempotent; never overwrites admin edits."""
    from app.ai.tasks import DEFAULT_ROUTES

    existing = set(
        (await db.execute(select(AIRoute.task_type))).scalars().all()
    )
    added = 0
    for task_type, cfg in DEFAULT_ROUTES.items():
        if str(task_type) in existing:
            continue
        db.add(
            AIRoute(
                task_type=str(task_type),
                primary_model=cfg["primary_model"],
                fallbacks=list(cfg.get("fallbacks", [])),
                params=dict(cfg.get("params", {})),
            )
        )
        added += 1
    if added:
        await db.commit()
    return added


async def heal_stale_routes(db: AsyncSession) -> list[str]:
    """Re-point any route whose stored primary model no longer exists upstream.

    Model catalogs churn — providers retire slugs. A stored route pointing at a
    retired model still *works* (the fallback chain covers it) but wastes a 404
    round-trip on every single call and hides the problem. On startup we compare
    stored primaries against the live catalog and reset the dead ones to the
    current defaults.

    Only routes that still match a *previous default* are touched, so a deliberate
    admin choice is never silently overwritten — if an admin pinned a model that
    later dies, the fallback chain handles it and the log tells them.
    """
    from app.ai.openrouter import fetch_catalog
    from app.ai.tasks import DEFAULT_ROUTES, NON_CHAT_TASKS

    try:
        catalog = await fetch_catalog()
    except Exception as exc:
        log.warning("route_heal_skipped_no_catalog", error=str(exc)[:200])
        return []

    live = {m["id"] for m in catalog}
    if not live:
        return []

    healed: list[str] = []
    non_chat = {str(t) for t in NON_CHAT_TASKS}
    rows = (await db.execute(select(AIRoute))).scalars().all()
    for row in rows:
        default = DEFAULT_ROUTES.get(row.task_type)

        # Audio/embedding models aren't in the chat catalog, so absence there
        # proves nothing — we can't verify them. But `updated_by IS NULL` means no
        # admin has ever edited this route, so it's still just our seeded default
        # and is safe to re-sync when the shipped default has moved on.
        if row.task_type in non_chat:
            if (
                default
                and row.updated_by is None
                and row.primary_model != default["primary_model"]
            ):
                log.info(
                    "ai_route_default_resynced",
                    task=row.task_type,
                    was=row.primary_model,
                    now=default["primary_model"],
                )
                row.primary_model = default["primary_model"]
                row.fallbacks = list(default.get("fallbacks", []))
                healed.append(row.task_type)
            continue

        if row.primary_model in live:
            continue
        default = DEFAULT_ROUTES.get(row.task_type)
        if not default or default["primary_model"] == row.primary_model:
            # Our own default is stale too, or this is an admin pin — leave it and
            # let the fallback chain carry the traffic.
            log.warning(
                "ai_route_primary_missing_upstream",
                task=row.task_type,
                model=row.primary_model,
            )
            continue
        log.info(
            "ai_route_healed",
            task=row.task_type,
            was=row.primary_model,
            now=default["primary_model"],
        )
        row.primary_model = default["primary_model"]
        row.fallbacks = list(default.get("fallbacks", []))
        healed.append(row.task_type)

    if healed:
        await db.commit()
    return healed


# ── Cache ─────────────────────────────────────────────────────────────────────


def cache_key(task_type: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:32]
    return f"ai:{task_type}:{digest}"


# ── Usage accounting ──────────────────────────────────────────────────────────


async def record_usage(
    db: AsyncSession, *, user_id: Any | None, task_type: str, result: AIResult
) -> None:
    db.add(
        AIUsage(
            user_id=user_id,
            task_type=str(task_type),
            model_used=result.model_used,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_micro_usd=result.cost_micro_usd,
            latency_ms=result.latency_ms,
            from_cache=result.from_cache,
            fallback_used=result.fallback_used,
        )
    )
    await db.commit()


def _extract_usage(msg: BaseMessage) -> tuple[int, int]:
    """Token counts from a LangChain response, across provider shapes."""
    if isinstance(msg, AIMessage):
        um = getattr(msg, "usage_metadata", None)
        if um:
            return int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
    meta = getattr(msg, "response_metadata", {}) or {}
    tu = meta.get("token_usage") or meta.get("usage") or {}
    return (
        int(tu.get("prompt_tokens", 0) or 0),
        int(tu.get("completion_tokens", 0) or 0),
    )


# Errors worth failing over to the next model. Anything else (e.g. a bad request
# we constructed) is a bug and should surface immediately, not silently retry.
_RETRYABLE = (
    "rate limit", "rate_limit", "429",
    "timeout", "timed out",
    "500", "502", "503", "504",
    "overloaded", "capacity", "unavailable",
    "model_not_found", "no endpoints", "not a valid model",
)


def _is_retryable(exc: Exception) -> bool:
    blob = f"{type(exc).__name__}: {exc}".lower()
    return any(tok in blob for tok in _RETRYABLE)


# ── The router ────────────────────────────────────────────────────────────────


async def complete(
    db: AsyncSession,
    *,
    task_type: TaskType | str,
    messages: list[BaseMessage],
    user_id: Any | None = None,
    model_override: str | None = None,
    params_override: dict[str, Any] | None = None,
    redis: Any | None = None,
) -> AIResult:
    """Run one non-streaming completion for `task_type`, with fallbacks.

    Raises ``AllModelsFailed`` only after every model in the chain has failed.
    """
    if str(task_type) in {str(t) for t in NON_CHAT_TASKS}:
        # Embeddings and audio use dedicated OpenRouter endpoints, not
        # /chat/completions. Sending them here would fail confusingly upstream.
        raise ValueError(
            f"'{task_type}' is not a chat task — dispatch it via app.ai.audio "
            "or app.ai.embeddings instead of router.complete()."
        )

    policy = await load_policy(db, str(task_type))
    params = {**policy.params, **(params_override or {})}
    chain = [model_override] if model_override else policy.chain

    # Deterministic tasks (translate, vocab examples) are cached — the single
    # biggest cost lever for a vocabulary-heavy product.
    ck = None
    if redis is not None and policy.cacheable and not model_override:
        ck = cache_key(str(task_type), [m.content for m in messages])
        try:
            if hit := await redis.get(ck):
                cached = json.loads(hit)
                result = AIResult(**cached)
                result.from_cache = True
                result.latency_ms = 0
                await record_usage(db, user_id=user_id, task_type=str(task_type), result=result)
                return result
        except Exception as exc:  # cache is best-effort, never fatal
            log.warning("ai_cache_read_failed", error=str(exc))

    attempts: list[dict[str, Any]] = []
    last_exc: Exception | None = None

    for idx, model in enumerate(chain):
        started = time.perf_counter()
        try:
            llm = make_llm(model, streaming=False, **params)
            msg = await llm.ainvoke(messages)
            elapsed = int((time.perf_counter() - started) * 1000)

            t_in, t_out = _extract_usage(msg)
            cost_usd, cost_micro = await estimate_cost(model, t_in, t_out)

            result = AIResult(
                text=str(msg.content or ""),
                model_used=model,
                tokens_in=t_in,
                tokens_out=t_out,
                cost_usd=cost_usd,
                cost_micro_usd=cost_micro,
                latency_ms=elapsed,
                fallback_used=idx > 0,
                attempts=attempts,
            )

            if ck is not None:
                try:
                    await redis.setex(
                        ck,
                        policy.cache_ttl,
                        json.dumps(
                            {
                                "text": result.text,
                                "model_used": result.model_used,
                                "tokens_in": t_in,
                                "tokens_out": t_out,
                                "cost_usd": cost_usd,
                                "cost_micro_usd": cost_micro,
                            }
                        ),
                    )
                except Exception as exc:
                    log.warning("ai_cache_write_failed", error=str(exc))

            if idx > 0:
                # A spike in these means the primary model is degraded.
                log.warning(
                    "ai_fallback_used",
                    task=str(task_type),
                    primary=chain[0],
                    used=model,
                    skipped=idx,
                )

            await record_usage(db, user_id=user_id, task_type=str(task_type), result=result)
            return result

        except UpstreamError:
            raise  # misconfiguration (e.g. missing key) — no point trying other models
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            retryable = _is_retryable(exc)
            attempts.append(
                {
                    "model": model,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "ms": elapsed,
                    "retryable": retryable,
                }
            )
            log.warning(
                "ai_model_attempt_failed",
                task=str(task_type),
                model=model,
                retryable=retryable,
                error=str(exc)[:300],
            )
            last_exc = exc
            if not retryable and idx == 0 and len(chain) > 1:
                # Still try fallbacks — a provider-specific quirk shouldn't
                # break the feature outright.
                continue

    log.error("ai_all_models_failed", task=str(task_type), attempts=attempts)
    raise AllModelsFailed(
        "All AI models failed for this request. Please try again in a moment."
    ) from last_exc
