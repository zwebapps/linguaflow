"""Admin API — knowledge-base ingestion + AI routing/usage control (API_CONTRACT.md §8).

Every route here is `CurrentAdmin`-gated. Mounted at `/admin` (see
app/api/v1/__init__.py), so paths below are relative: `/documents`, `/ai-routes`, …
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.ai.openrouter import fetch_catalog
from app.ai.tasks import TaskType
from app.core.config import settings
from app.core.deps import CurrentAdmin, DbSession
from app.core.errors import NotFound, UpstreamError, ValidationError
from app.db.models import AIRoute, AIUsage, Document, ExperimentConfig, FeedSource, RagEvent
from app.rag.experiments import DEFAULT_EXPERIMENT, summarise
from app.rag.parsers import validate_public_url
from app.rag.vector_store import get_vector_store
from app.workers.ingest import enqueue

log = structlog.get_logger(__name__)
router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]
DocumentStatus = Literal["pending", "processing", "ready", "failed"]

# Uploads are written here, one file per document — see `_save_upload`.
UPLOAD_DIR = Path("var/uploads")

_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".docx": "docx",
    ".md": "md",
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
}


# ── Schemas ────────────────────────────────────────────────────────────────────


class DocumentCreated(BaseModel):
    """The §8 "202 Accepted" shape for both upload and link creation."""

    id: str
    title: str
    status: str
    source_type: str
    created_at: Any


class DocumentListItem(BaseModel):
    id: str
    title: str
    source_type: str
    source_url: str | None
    cefr_level: str | None
    skill: str | None
    status: str
    error: str | None
    chunk_count: int
    created_at: Any
    updated_at: Any


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None = None


class LinkDocumentRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    source_type: Literal["web", "youtube", "rss"]
    cefr_level: CEFR | None = None
    skill: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=500)


class AIRouteOut(BaseModel):
    task_type: str
    primary_model: str
    fallbacks: list[str]
    params: dict[str, Any]
    updated_at: Any


class AIRoutesResponse(BaseModel):
    routes: list[AIRouteOut]


class UpdateAIRouteRequest(BaseModel):
    primary_model: str = Field(min_length=1, max_length=120)
    fallbacks: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    id: str | None
    name: str | None
    context_length: int | None
    prompt_usd_per_1k: float
    completion_usd_per_1k: float
    supports_tools: bool


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class UsageTotal(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    calls: int
    cache_hit_rate: float


class UsageSeriesPoint(BaseModel):
    key: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    calls: int


class UsageResponse(BaseModel):
    total: UsageTotal
    series: list[UsageSeriesPoint]


class FeedCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    cefr_level: CEFR | None = None
    skill: str | None = Field(default=None, max_length=20)
    poll_interval_minutes: int = Field(default=1440, ge=5, le=10080)


class FeedOut(BaseModel):
    # NOTE: `skill` is intentionally absent — the §8 feed item shape omits it
    # even though POST accepts it (it still flows onto every ingested Document).
    id: str
    url: str
    cefr_level: str | None
    poll_interval_minutes: int
    last_polled_at: Any
    is_active: bool
    items_ingested: int


class FeedsResponse(BaseModel):
    items: list[FeedOut]


# ── View helpers ───────────────────────────────────────────────────────────────


def _created_view(document: Document) -> DocumentCreated:
    return DocumentCreated(
        id=str(document.id),
        title=document.title,
        status=document.status,
        source_type=document.source_type,
        created_at=document.created_at,
    )


def _document_view(document: Document) -> DocumentListItem:
    return DocumentListItem(
        id=str(document.id),
        title=document.title,
        source_type=document.source_type,
        source_url=document.source_url,
        cefr_level=document.cefr_level,
        skill=document.skill,
        status=document.status,
        error=document.error,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _route_view(route: AIRoute) -> AIRouteOut:
    return AIRouteOut(
        task_type=route.task_type,
        primary_model=route.primary_model,
        fallbacks=list(route.fallbacks or []),
        params=dict(route.params or {}),
        updated_at=route.updated_at,
    )


def _feed_view(feed: FeedSource) -> FeedOut:
    return FeedOut(
        id=str(feed.id),
        url=feed.url,
        cefr_level=feed.cefr_level,
        poll_interval_minutes=feed.poll_interval_minutes,
        last_polled_at=feed.last_polled_at,
        is_active=feed.is_active,
        items_ingested=feed.items_ingested,
    )


# ── Upload plumbing ────────────────────────────────────────────────────────────


def _validate_extension(filename: str | None) -> str:
    """→ the `source_type` for an allowed extension; raises on anything else."""
    ext = Path(filename or "").suffix.lower()
    source_type = _ALLOWED_EXTENSIONS.get(ext)
    if source_type is None:
        allowed = ", ".join(sorted({v for v in _ALLOWED_EXTENSIONS.values()}))
        raise ValidationError(
            f"Unsupported file type: {ext or '(none)'}. Allowed: {allowed}.",
            details=[{"field": "file", "issue": "unsupported extension"}],
        )
    return source_type


async def _save_upload(file: UploadFile) -> tuple[str, str]:
    """Stream `file` to `UPLOAD_DIR`, enforcing the size cap as bytes arrive.

    Never buffers the whole body in memory — a 25 MB cap is generous enough
    that a naive `await file.read()` would work fine today, but reading a
    request body fully before validating its size is exactly the pattern that
    turns "reject big uploads" into "OOM on big uploads" the day someone raises
    MAX_UPLOAD_MB or a client lies about Content-Length.
    """
    source_type = _validate_extension(file.filename)
    ext = Path(file.filename or "").suffix.lower()
    await asyncio.to_thread(UPLOAD_DIR.mkdir, parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    limit = settings.max_upload_bytes

    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValidationError(
                        f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit."
                    )
                out.write(chunk)
    except Exception:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise
    finally:
        await file.close()

    return str(dest), source_type


# ── Documents ──────────────────────────────────────────────────────────────────


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    db: DbSession,
    admin: CurrentAdmin,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=500)] = None,
    cefr_level: Annotated[CEFR | None, Form()] = None,
    skill: Annotated[str | None, Form(max_length=20)] = None,
) -> DocumentCreated:
    storage_path, source_type = await _save_upload(file)

    document = Document(
        created_by=admin.id,
        title=(title or Path(file.filename or "").stem or "Untitled").strip(),
        source_type=source_type,
        storage_path=storage_path,
        cefr_level=cefr_level,
        skill=skill,
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await enqueue(document.id)
    log.info("document_upload_queued", document_id=str(document.id), source_type=source_type)
    return _created_view(document)


@router.post("/documents/link", status_code=status.HTTP_202_ACCEPTED)
async def link_document(
    payload: LinkDocumentRequest, db: DbSession, admin: CurrentAdmin
) -> DocumentCreated:
    validate_public_url(payload.url)

    document = Document(
        created_by=admin.id,
        title=(payload.title or payload.url).strip(),
        source_type=payload.source_type,
        source_url=payload.url,
        cefr_level=payload.cefr_level,
        skill=payload.skill,
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await enqueue(document.id)
    log.info("document_link_queued", document_id=str(document.id), source_type=payload.source_type)
    return _created_view(document)


@router.get("/documents")
async def list_documents(
    db: DbSession,
    admin: CurrentAdmin,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> DocumentPage:
    stmt = select(Document)
    if status_filter is not None:
        stmt = stmt.where(Document.status == status_filter)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError as exc:
            raise ValidationError("Invalid cursor.") from exc
        stmt = stmt.where(Document.created_at < cursor_dt)

    stmt = stmt.order_by(Document.created_at.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return DocumentPage(
        items=[_document_view(d) for d in rows],
        next_cursor=rows[-1].created_at.isoformat() if (has_more and rows) else None,
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, db: DbSession, admin: CurrentAdmin) -> Response:
    document = await db.get(Document, document_id)
    if document is None:
        raise NotFound("Document not found.")

    await get_vector_store().delete_by_document(document.collection, str(document.id))
    if document.storage_path:
        await asyncio.to_thread(Path(document.storage_path).unlink, missing_ok=True)

    await db.delete(document)  # cascades to `chunks` (relationship + FK)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/{document_id}/reingest", status_code=status.HTTP_202_ACCEPTED)
async def reingest_document(
    document_id: uuid.UUID, db: DbSession, admin: CurrentAdmin
) -> DocumentCreated:
    document = await db.get(Document, document_id)
    if document is None:
        raise NotFound("Document not found.")

    document.status = "pending"
    document.error = None
    await db.commit()

    await enqueue(document.id)
    log.info("document_reingest_queued", document_id=str(document.id))
    return _created_view(document)


# ── AI routing ─────────────────────────────────────────────────────────────────


@router.get("/ai-routes")
async def list_ai_routes(db: DbSession, admin: CurrentAdmin) -> AIRoutesResponse:
    rows = (await db.execute(select(AIRoute).order_by(AIRoute.task_type))).scalars().all()
    return AIRoutesResponse(routes=[_route_view(r) for r in rows])


async def _validate_model_id(model_id: str) -> None:
    """Best-effort check against the live OpenRouter catalog.

    A flaky third party must never block an admin's edit — if the catalog call
    itself fails we log and allow the write; we only hard-reject when the
    catalog is reachable AND the model genuinely isn't in it.
    """
    try:
        catalog = await fetch_catalog()
    except UpstreamError as exc:
        log.warning("ai_route_model_validation_skipped", model=model_id, error=str(exc))
        return
    known_ids = {m["id"] for m in catalog}
    if model_id not in known_ids:
        raise ValidationError(f"Unknown model id: {model_id!r}. Check GET /admin/models.")


@router.put("/ai-routes/{task_type}")
async def update_ai_route(
    task_type: str, payload: UpdateAIRouteRequest, db: DbSession, admin: CurrentAdmin
) -> AIRouteOut:
    if task_type not in {t.value for t in TaskType}:
        raise ValidationError(f"Unknown task_type: {task_type!r}.")

    await _validate_model_id(payload.primary_model)
    for fallback in payload.fallbacks:
        await _validate_model_id(fallback)

    row = await db.get(AIRoute, task_type)
    if row is None:
        row = AIRoute(task_type=task_type)
        db.add(row)

    row.primary_model = payload.primary_model
    row.fallbacks = payload.fallbacks
    row.params = payload.params
    row.updated_by = admin.id
    await db.commit()
    await db.refresh(row)

    log.info("ai_route_updated", task_type=task_type, model=payload.primary_model, by=str(admin.id))
    return _route_view(row)


@router.get("/models")
async def list_models(admin: CurrentAdmin) -> ModelsResponse:
    return ModelsResponse(models=await fetch_catalog())


# ── Usage ──────────────────────────────────────────────────────────────────────


def _usage_group_key(row: AIUsage, group_by: str) -> str:
    if group_by == "model":
        return row.model_used
    if group_by == "task":
        return row.task_type
    if group_by == "user":
        return str(row.user_id) if row.user_id else "anonymous"
    return row.created_at.date().isoformat()  # "day" (default)


def _micro_to_usd(micro_usd: int) -> float:
    return round(micro_usd / 1_000_000, 6)


def aggregate_usage(rows: list[AIUsage], group_by: str) -> UsageResponse:
    """Pure aggregation over already-fetched rows — kept separate from the DB
    query so the cost/cache-hit-rate maths is unit-testable with no Postgres."""
    tokens_in = tokens_out = calls = cache_hits = 0
    cost_micro = 0
    buckets: dict[str, dict[str, int]] = {}

    for row in rows:
        tokens_in += row.tokens_in
        tokens_out += row.tokens_out
        cost_micro += row.cost_micro_usd
        calls += 1
        if row.from_cache:
            cache_hits += 1

        key = _usage_group_key(row, group_by)
        bucket = buckets.setdefault(
            key, {"tokens_in": 0, "tokens_out": 0, "cost_micro": 0, "calls": 0}
        )
        bucket["tokens_in"] += row.tokens_in
        bucket["tokens_out"] += row.tokens_out
        bucket["cost_micro"] += row.cost_micro_usd
        bucket["calls"] += 1

    series = [
        UsageSeriesPoint(
            key=key,
            tokens_in=bucket["tokens_in"],
            tokens_out=bucket["tokens_out"],
            cost_usd=_micro_to_usd(bucket["cost_micro"]),
            calls=bucket["calls"],
        )
        for key, bucket in sorted(buckets.items())
    ]
    total = UsageTotal(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_micro_to_usd(cost_micro),
        calls=calls,
        cache_hit_rate=round(cache_hits / calls, 4) if calls else 0.0,
    )
    return UsageResponse(total=total, series=series)


@router.get("/usage")
async def get_usage(
    db: DbSession,
    admin: CurrentAdmin,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    group_by: Literal["day", "model", "task", "user"] = Query(default="day"),
) -> UsageResponse:
    stmt = select(AIUsage)
    if from_ is not None:
        stmt = stmt.where(AIUsage.created_at >= from_)
    if to is not None:
        stmt = stmt.where(AIUsage.created_at <= to)

    rows = (await db.execute(stmt)).scalars().all()
    return aggregate_usage(list(rows), group_by)


# ── Feeds ──────────────────────────────────────────────────────────────────────


@router.get("/feeds")
async def list_feeds(db: DbSession, admin: CurrentAdmin) -> FeedsResponse:
    rows = (
        await db.execute(select(FeedSource).order_by(FeedSource.created_at.desc()))
    ).scalars().all()
    return FeedsResponse(items=[_feed_view(f) for f in rows])


@router.post("/feeds", status_code=status.HTTP_201_CREATED)
async def create_feed(payload: FeedCreateRequest, db: DbSession, admin: CurrentAdmin) -> FeedOut:
    validate_public_url(payload.url)

    feed = FeedSource(
        created_by=admin.id,
        url=payload.url,
        cefr_level=payload.cefr_level,
        skill=payload.skill,
        poll_interval_minutes=payload.poll_interval_minutes,
    )
    db.add(feed)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValidationError("A feed with that URL already exists.") from exc
    await db.refresh(feed)
    return _feed_view(feed)


@router.delete("/feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(feed_id: uuid.UUID, db: DbSession, admin: CurrentAdmin) -> Response:
    feed = await db.get(FeedSource, feed_id)
    if feed is None:
        raise NotFound("Feed not found.")
    await db.delete(feed)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── A/B experiments over RAG strategies ───────────────────────────────────────


class ExperimentOut(BaseModel):
    name: str
    enabled: bool
    arms: dict[str, float]
    description: str | None = None
    updated_at: Any | None = None


class ExperimentsResponse(BaseModel):
    experiments: list[ExperimentOut]
    # What an arm may be. The admin UI builds its strategy dropdown from this,
    # so the list has exactly one home (rag/experiments.SUPPORTED_STRATEGIES).
    available_arms: list[str]


class ExperimentUpsertRequest(BaseModel):
    enabled: bool
    # Weights are normalised at read time, so {hybrid: 1, dense: 1} means 50/50.
    arms: dict[str, float] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("arms")
    @classmethod
    def _valid_arms(cls, v: dict[str, float]) -> dict[str, float]:
        # Derived, not restated: a strategy added to the retriever becomes an
        # allowed arm here without anyone remembering this validator exists.
        from app.rag.experiments import SUPPORTED_STRATEGIES

        allowed = set(SUPPORTED_STRATEGIES)
        bad = set(v) - allowed
        if bad:
            raise ValueError(
                f"unknown arm(s): {', '.join(sorted(bad))}. Allowed: {', '.join(sorted(allowed))}"
            )
        if all(w <= 0 for w in v.values()):
            raise ValueError("at least one arm needs a positive weight")
        if any(w < 0 for w in v.values()):
            raise ValueError("arm weights cannot be negative")
        return v


class ExperimentResultsResponse(BaseModel):
    experiment: str
    total_events: int
    arms: list[dict[str, Any]]
    winner: str | None = None
    note: str


@router.get("/experiments", response_model=ExperimentsResponse)
async def list_experiments(db: DbSession, admin: CurrentAdmin) -> ExperimentsResponse:
    """Configured experiments, including the shipped default when unsaved."""
    rows = (await db.execute(select(ExperimentConfig))).scalars().all()
    out = [
        ExperimentOut(
            name=r.name,
            enabled=r.enabled,
            arms={str(k): float(v) for k, v in (r.arms or {}).items()},
            description=r.description,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    if not any(o.name == DEFAULT_EXPERIMENT.name for o in out):
        out.append(
            ExperimentOut(
                name=DEFAULT_EXPERIMENT.name,
                enabled=DEFAULT_EXPERIMENT.enabled,
                arms=dict(DEFAULT_EXPERIMENT.arms),
                description="Shipped default (not yet saved to the database).",
            )
        )
    from app.rag.experiments import SUPPORTED_STRATEGIES

    return ExperimentsResponse(experiments=out, available_arms=list(SUPPORTED_STRATEGIES))


@router.put("/experiments/{name}", response_model=ExperimentOut)
async def upsert_experiment(
    name: str, payload: ExperimentUpsertRequest, db: DbSession, admin: CurrentAdmin
) -> ExperimentOut:
    """Start, stop, or re-weight an experiment at runtime — no redeploy."""
    row = await db.get(ExperimentConfig, name)
    if row is None:
        row = ExperimentConfig(name=name)
        db.add(row)
    row.enabled = payload.enabled
    row.arms = {k: float(v) for k, v in payload.arms.items()}
    row.description = payload.description
    row.updated_by = admin.id
    await db.commit()
    await db.refresh(row)
    log.info("experiment_updated", experiment=name, enabled=row.enabled, arms=row.arms)
    return ExperimentOut(
        name=row.name,
        enabled=row.enabled,
        arms={str(k): float(v) for k, v in (row.arms or {}).items()},
        description=row.description,
        updated_at=row.updated_at,
    )


@router.get("/experiments/{name}/results", response_model=ExperimentResultsResponse)
async def experiment_results(
    name: str,
    db: DbSession,
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 10_000,
) -> ExperimentResultsResponse:
    """Per-arm outcomes for a running experiment.

    Aggregated from `rag_events` — i.e. from what learners actually received —
    rather than by re-running retrieval, which would measure today's index instead
    of the one that served them.
    """
    rows = (
        await db.execute(
            select(RagEvent)
            .where(RagEvent.experiment == name)
            .order_by(RagEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    stats = summarise(
        [
            {
                "arm": r.arm,
                "n_results": r.n_results,
                "top_score": r.top_score,
                "latency_ms": r.latency_ms,
            }
            for r in rows
        ]
    )

    # `summarise` sorts best-first, but a handful of events proves nothing — say so
    # rather than letting an admin read noise as a result.
    enough = len(rows) >= 30
    return ExperimentResultsResponse(
        experiment=name,
        total_events=len(rows),
        arms=stats,
        winner=(stats[0]["arm"] if stats and enough else None),
        note=(
            "Ranked by mean usable results, then relevance."
            if enough
            else f"Only {len(rows)} events recorded — too few to call a winner (need 30+)."
        ),
    )


# ── Prompt management ─────────────────────────────────────────────────────────
# The AI's editable voice: DB overrides over the code defaults, validated so a
# broken template can never reach a learner. See app.ai.prompt_registry.


class PromptOut(BaseModel):
    key: str
    title: str
    description: str
    placeholders: list[str]
    default: str
    override: str | None
    active_source: str  # "default" | "override"
    updated_at: str | None


class PromptUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


@router.get("/prompts")
async def list_prompts(db: DbSession, admin: CurrentAdmin) -> list[PromptOut]:
    from app.ai import prompt_registry as reg
    from app.db.models import PromptOverride

    rows = {
        r.key: r
        for r in (await db.execute(select(PromptOverride))).scalars()
        if r.key in reg.REGISTRY
    }
    return [
        PromptOut(
            key=spec.key,
            title=spec.title,
            description=spec.description,
            placeholders=sorted(spec.placeholders),
            default=spec.default,
            override=rows[spec.key].content if spec.key in rows else None,
            active_source="override" if spec.key in rows else "default",
            updated_at=(
                rows[spec.key].updated_at.isoformat() if spec.key in rows else None
            ),
        )
        for spec in reg.REGISTRY.values()
    ]


@router.put("/prompts/{key}")
async def update_prompt(
    key: str, payload: PromptUpdateRequest, db: DbSession, admin: CurrentAdmin
) -> PromptOut:
    from app.ai import prompt_registry as reg
    from app.db.models import PromptOverride

    spec = reg.REGISTRY.get(key)
    if spec is None:
        raise NotFound(f"No editable prompt named '{key}'.")
    content = payload.content.strip()
    reg.validate_override(spec, content)

    row = (
        await db.execute(select(PromptOverride).where(PromptOverride.key == key))
    ).scalar_one_or_none()
    if row is None:
        row = PromptOverride(key=key, content=content, updated_by=admin.id)
        db.add(row)
    else:
        row.content = content
        row.updated_by = admin.id
    await db.commit()
    await db.refresh(row)
    log.info("prompt_override_saved", key=key, admin_id=str(admin.id))
    return PromptOut(
        key=spec.key,
        title=spec.title,
        description=spec.description,
        placeholders=sorted(spec.placeholders),
        default=spec.default,
        override=row.content,
        active_source="override",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/prompts/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_prompt(key: str, db: DbSession, admin: CurrentAdmin) -> Response:
    """Deleting the override IS the reset — the code default takes over."""
    from app.ai import prompt_registry as reg
    from app.db.models import PromptOverride

    if key not in reg.REGISTRY:
        raise NotFound(f"No editable prompt named '{key}'.")
    row = (
        await db.execute(select(PromptOverride).where(PromptOverride.key == key))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
        log.info("prompt_override_reset", key=key, admin_id=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
