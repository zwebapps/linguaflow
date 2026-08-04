"""Application settings.

Everything is env-driven so the same image runs locally (docker-compose) and in
production (Supabase + Qdrant Cloud + Render) with no code changes.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV: Literal["local", "ci", "staging", "production"] = "local"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:3000"

    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET: str = "dev-only-change-me-to-32-plus-random-chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7

    # Seed the starter corpus on boot even outside local/ci. Off by default so
    # a real production instance never surprises anyone with demo content; a
    # portfolio deployment sets it to start with a full library.
    SEED_ON_BOOT: bool = False

    # Where verification links and OAuth round-trips send the browser.
    PUBLIC_APP_URL: str = "http://localhost:3010"
    # Email delivery. "console" logs the message and writes it to var/outbox/
    # so dev can click the link; wire a real provider here before production.
    EMAIL_SINK: Literal["console"] = "console"
    VERIFY_TOKEN_TTL_HOURS: int = 24

    # ── OAuth sign-in (Google / Microsoft). Empty = the provider's button is
    # hidden and its endpoints answer 503. Fill these from the provider console:
    # Google Cloud Console → OAuth client; Azure Portal → App registration.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    # Base URL the provider redirects back to (this API's public origin).
    OAUTH_CALLBACK_BASE: str = "http://localhost:8000"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://linguaflow:linguaflow@localhost:5442/linguaflow"
    )

    # ── Vector store ──────────────────────────────────────────────────────────
    VECTOR_BACKEND: Literal["qdrant", "pgvector"] = "qdrant"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6390/0"

    # ── OpenRouter (LLM gateway) ──────────────────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_APP_URL: str = "http://localhost:3000"
    OPENROUTER_APP_TITLE: str = "LinguaFlow AI"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # OpenRouter serves embeddings (POST /embeddings), so the default needs no
    # model download. Switch to "local" for fully-offline dev — that requires the
    # optional `local-embeddings` extra (pulls in torch).
    EMBEDDING_BACKEND: Literal["local", "openrouter"] = "openrouter"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ── Voice (OpenRouter audio endpoints) ────────────────────────────────────
    STT_MODEL: str = "google/gemini-2.5-flash"
    TTS_MODEL: str = "openai/gpt-4o-mini-tts"
    TTS_VOICE: str = "alloy"
    MAX_AUDIO_MB: int = 20
    SPEECH_LANGUAGE: str = "de"

    # ── Ingestion ─────────────────────────────────────────────────────────────
    MAX_UPLOAD_MB: int = 25
    CHUNK_TOKENS: int = 600
    CHUNK_OVERLAP_TOKENS: int = 90

    # ── Retrieval ─────────────────────────────────────────────────────────────
    RETRIEVAL_TOP_K: int = 6
    SEARCH_STRATEGY: Literal["hybrid", "dense", "keyword"] = "hybrid"

    # ── Limits ────────────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 30

    # How long the ingest worker blocks on BLPOP per poll. Every poll is one
    # billable command on a managed Redis: at 5s that is ~430k commands/month
    # idle — essentially all of Upstash's 500k free tier spent on an empty
    # queue. 30s costs ~86k/month and adds at most 30s of pickup latency.
    INGEST_BLOCK_SECONDS: int = 30
    FREE_MONTHLY_AI_CALLS: int = 500

    # ── Bootstrap admin ───────────────────────────────────────────────────────
    ADMIN_EMAIL: str = "admin@linguaflow.dev"
    ADMIN_PASSWORD: str = "changeme123"

    # Demo learner (local dev only — matches frontend login defaults)
    DEMO_LEARNER_EMAIL: str = "learner@deutschflow.ai"
    DEMO_LEARNER_PASSWORD: str = "demo12345"

    # ── Derived ───────────────────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def max_audio_bytes(self) -> int:
        return self.MAX_AUDIO_MB * 1024 * 1024

    @property
    def is_local(self) -> bool:
        return self.APP_ENV in ("local", "ci")

    @field_validator("JWT_SECRET")
    @classmethod
    def _secret_must_be_strong_outside_local(cls, v: str, info) -> str:
        env = (info.data or {}).get("APP_ENV", "local")
        if env in ("staging", "production") and (
            len(v) < 32 or v.startswith("dev-only")
        ):
            raise ValueError("JWT_SECRET must be a strong 32+ char secret outside local")
        return v

    @field_validator("ADMIN_PASSWORD")
    @classmethod
    def _admin_password_must_be_changed_outside_local(cls, v: str, info) -> str:
        """Refuse to boot a deployed instance with the shipped admin password.

        `bootstrap.ensure_admin()` creates a `role="admin"` account on every
        startup. With the default password that is a publicly-known credential to
        the entire /admin surface (knowledge-base ingestion, server-side URL
        fetching, model routing, all-user usage data) — so this fails fast rather
        than starting an instance anyone can take over.
        """
        env = (info.data or {}).get("APP_ENV", "local")
        if env in ("staging", "production") and (
            v == "changeme123" or len(v) < 12
        ):
            raise ValueError(
                "ADMIN_PASSWORD must be changed from the default and be at least "
                "12 characters outside local/ci"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
