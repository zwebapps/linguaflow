"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("starting", env=settings.APP_ENV, vector_backend=settings.VECTOR_BACKEND)

    # Seed the AI routing table and the bootstrap admin so a fresh clone is usable.
    from app.db.session import SessionLocal
    from app.services.bootstrap import bootstrap

    try:
        async with SessionLocal() as db:
            await bootstrap(db)
    except Exception as exc:
        # A DB that isn't up yet shouldn't stop the process — /readyz will report it.
        log.error("bootstrap_failed", error=str(exc))

    async def _seed_library_background() -> None:
        from app.services.seed_kb import ensure_seed_corpus

        try:
            async with SessionLocal() as db:
                await ensure_seed_corpus(db)
        except Exception as exc:
            log.error("seed_corpus_failed", error=str(exc))

    if settings.is_local:
        asyncio.create_task(_seed_library_background())

    yield

    from app.core.cache import close_client

    await close_client()
    log.info("stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="LinguaFlow AI API",
        version="0.1.0",
        description="AI-native language learning platform — RAG + tool-calling tutor.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    cors_kwargs: dict = {
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["Retry-After"],
    }
    if settings.APP_ENV == "local":
        # Next.js often picks 3001+ when 3000 is busy — avoid "Failed to fetch" from CORS.
        cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        cors_kwargs["allow_origins"] = settings.cors_origin_list
    else:
        cors_kwargs["allow_origins"] = settings.cors_origin_list

    app.add_middleware(CORSMiddleware, **cors_kwargs)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Attach a request id so a client error message can be traced to a log line."""
        rid = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "path")
        response.headers["X-Request-Id"] = rid
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, object]:
        from sqlalchemy import text

        from app.core.cache import ping as redis_ping
        from app.db.session import SessionLocal

        db_ok = False
        try:
            async with SessionLocal() as s:
                await s.execute(text("SELECT 1"))
                db_ok = True
        except Exception as exc:
            log.warning("readyz_db_failed", error=str(exc))

        vector_ok = False
        try:
            from app.rag.vector_store import get_vector_store

            vector_ok = await get_vector_store().health()
        except Exception as exc:
            log.warning("readyz_vector_failed", error=str(exc))

        return {
            "status": "ok" if (db_ok and vector_ok) else "degraded",
            "db": db_ok,
            "vector_store": vector_ok,
            "redis": await redis_ping(),
            "llm": bool(settings.OPENROUTER_API_KEY),
        }

    return app


app = create_app()
