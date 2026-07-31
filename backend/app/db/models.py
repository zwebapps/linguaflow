"""SQLAlchemy models — V1 schema.

Notes
-----
* V1 keeps auth local (``users.password_hash``). V2 swaps to Supabase Auth; the
  user row survives, only the credential columns stop being used.
* ``chunks`` always stores the chunk *text* even when Qdrant holds the vectors —
  Postgres stays the source of truth, the vector store is a derived index. It also
  gives the BM25 half of hybrid search something to read.
* Money is stored as integer micro-USD to avoid float drift.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── Identity ──────────────────────────────────────────────────────────────────


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="student", nullable=False)

    # Learning profile (set during onboarding)
    cefr_level: Mapped[str] = mapped_column(String(2), default="A1", nullable=False)
    goal: Mapped[str | None] = mapped_column(String(40))
    learning_style: Mapped[str | None] = mapped_column(String(20))
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    gloss_langs: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["en"])
    # The language the learner already speaks. Distinct from `gloss_langs` (which
    # dictionary entries are translated into): this is what the TUTOR explains in.
    # The prompt previously said "explain in the learner's language" without ever
    # telling the model what that was, so it silently defaulted to English.
    # `server_default` as well as `default`: adding a NOT NULL column to a table
    # that already has rows needs a DB-level default, or the migration fails on
    # every existing user.
    native_language: Mapped[str] = mapped_column(
        String(8), default="en", server_default="en", nullable=False
    )
    # The language being learned. German today; stored per-user so a second
    # target language is a content problem, not a schema migration.
    target_language: Mapped[str] = mapped_column(
        String(8), default="de", server_default="de", nullable=False
    )
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ── Knowledge base (admin-curated) ────────────────────────────────────────────


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    content_md: Mapped[str | None] = mapped_column(Text)  # extracted text, for Reading Mode

    cefr_level: Mapped[str | None] = mapped_column(String(2), index=True)
    skill: Mapped[str | None] = mapped_column(String(20), index=True)
    collection: Mapped[str] = mapped_column(
        String(50), default="grammar_documents", nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reading_minutes: Mapped[int | None] = mapped_column(Integer)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base, TimestampMixin):
    """One retrievable passage. Text lives here; vectors live here *or* in Qdrant."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500))
    page: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    cefr_level: Mapped[str | None] = mapped_column(String(2), index=True)
    skill: Mapped[str | None] = mapped_column(String(20))

    # Only populated when VECTOR_BACKEND=pgvector.
    embedding: Mapped[Any | None] = mapped_column(Vector(settings.EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunk_doc_ordinal"),
    )


class FeedSource(Base, TimestampMixin):
    __tablename__ = "feed_sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    cefr_level: Mapped[str | None] = mapped_column(String(2))
    skill: Mapped[str | None] = mapped_column(String(20))
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    last_seen_guid: Mapped[str | None] = mapped_column(Text)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ── Conversations ─────────────────────────────────────────────────────────────


class Thread(Base, TimestampMixin):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    model: Mapped[str | None] = mapped_column(String(120))
    sources: Mapped[list[dict] | None] = mapped_column(JSONB)
    tool_calls: Mapped[list[dict] | None] = mapped_column(JSONB)
    usage: Mapped[dict | None] = mapped_column(JSONB)

    thread: Mapped[Thread] = relationship(back_populates="messages")


# ── Vocabulary & SRS ──────────────────────────────────────────────────────────


class Vocabulary(Base, TimestampMixin):
    __tablename__ = "vocabulary"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    lemma: Mapped[str] = mapped_column(String(120), nullable=False)
    article: Mapped[str | None] = mapped_column(String(10))
    plural: Mapped[str | None] = mapped_column(String(120))
    pos: Mapped[str | None] = mapped_column(String(20))
    meaning: Mapped[str | None] = mapped_column(Text)
    ipa: Mapped[str | None] = mapped_column(String(120))
    examples: Mapped[list[dict] | None] = mapped_column(JSONB)
    meanings: Mapped[list[dict] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    card: Mapped[Flashcard | None] = relationship(
        back_populates="vocabulary", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "lemma", name="uq_vocab_user_lemma"),
    )


class Flashcard(Base, TimestampMixin):
    """SM-2 style scheduling state."""

    __tablename__ = "flashcards"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    vocabulary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vocabulary.id", ondelete="CASCADE"), unique=True
    )
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    last_grade: Mapped[str | None] = mapped_column(String(10))

    vocabulary: Mapped[Vocabulary] = relationship(back_populates="card")


# ── Assessment ────────────────────────────────────────────────────────────────


class Quiz(Base, TimestampMixin):
    """Generated quiz. `questions` keeps the answer key server-side only."""

    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    cefr_level: Mapped[str | None] = mapped_column(String(2))
    questions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    sources: Mapped[list[dict] | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)


class WritingSubmission(Base, TimestampMixin):
    __tablename__ = "writing_submissions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    prompt: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    target_level: Mapped[str | None] = mapped_column(String(2))
    scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cefr_estimate: Mapped[str | None] = mapped_column(String(2))
    corrections: Mapped[list[dict] | None] = mapped_column(JSONB)
    improved_version: Mapped[str | None] = mapped_column(Text)
    suggestions: Mapped[list[str] | None] = mapped_column(JSONB)


class TopicStat(Base, TimestampMixin):
    """Rolling per-topic accuracy — powers the weak-spots analysis."""

    __tablename__ = "topic_stats"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "topic", name="uq_topic_user"),)


class Activity(Base, TimestampMixin):
    __tablename__ = "activity"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_activity_user_day"),)


# ── AI plumbing ───────────────────────────────────────────────────────────────


class AIRoute(Base, TimestampMixin):
    """Task → model policy. Editable from the admin UI with no redeploy."""

    __tablename__ = "ai_routes"

    task_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    primary_model: Mapped[str] = mapped_column(String(120), nullable=False)
    fallbacks: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class ExperimentConfig(Base, TimestampMixin):
    """A/B experiment definition — editable at runtime, no redeploy.

    Same posture as `ai_routes`: the thing an operator needs to change mid-flight
    lives in the DB, not in the deployed image.
    """

    __tablename__ = "experiment_configs"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # arm name → traffic weight; normalised at read time so weights need not sum to 1.
    arms: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class RagEvent(Base):
    """One retrieval, tagged with the experiment arm that served it.

    Recorded per request rather than derived later: the winning arm can only be
    judged from what users actually got, and re-running retrieval afterwards would
    measure today's index, not the one that answered them.
    """

    __tablename__ = "rag_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    experiment: Mapped[str | None] = mapped_column(String(60), index=True)
    arm: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    n_results: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_rag_events_exp_arm", "experiment", "arm"),)


class AIUsage(Base):
    """One row per model call — powers cost dashboards and quota enforcement."""

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model_used: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)
