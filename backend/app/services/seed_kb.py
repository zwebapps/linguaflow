"""Starter knowledge-base corpus — shared by CLI and local bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Document
from app.rag.ingest import ingest_document

log = structlog.get_logger(__name__)

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"


@dataclass(slots=True)
class SeedDoc:
    filename: str
    title: str
    cefr_level: str
    skill: str


SEED_DOCS: tuple[SeedDoc, ...] = (
    SeedDoc("dativ.md", "Der Dativ", "A2", "grammar"),
    SeedDoc("praesens.md", "Das Präsens", "A1", "grammar"),
    SeedDoc("akkusativ_praepositionen.md", "Präpositionen mit Akkusativ", "A2", "grammar"),
    SeedDoc("ein_tag_im_park.md", "Ein Tag im Park", "A1", "reading"),
)


def embeddings_available() -> bool:
    if settings.EMBEDDING_BACKEND == "local":
        return True
    return bool(settings.OPENROUTER_API_KEY.strip())


async def seed_one_document(db: AsyncSession, spec: SeedDoc) -> bool:
    """Ingest one seed file if no document with this title exists. Returns True if ingested."""
    path = SEED_DIR / spec.filename
    if not path.exists():
        raise FileNotFoundError(f"Seed file missing: {path}")

    existing = (
        await db.execute(select(Document).where(Document.title == spec.title))
    ).scalar_one_or_none()
    if existing is not None:
        log.info("seed_kb_skip_existing", title=spec.title, status=existing.status)
        return False

    document = Document(
        title=spec.title,
        source_type="md",
        storage_path=str(path),
        cefr_level=spec.cefr_level,
        skill=spec.skill,
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    log.info("seed_kb_ingesting", title=spec.title, document_id=str(document.id))
    await ingest_document(db, document.id)
    await db.refresh(document)

    if document.status != "ready":
        raise RuntimeError(f"Seeding failed for {spec.title!r}: {document.error}")
    log.info("seed_kb_ready", title=spec.title, chunks=document.chunk_count)
    return True


async def ensure_seed_corpus(db: AsyncSession) -> int:
    """Ensure shipped seed documents exist (local/ci). Returns count newly ingested."""
    if not settings.is_local:
        return 0
    if not embeddings_available():
        log.warning(
            "seed_corpus_skipped",
            reason="Set OPENROUTER_API_KEY or EMBEDDING_BACKEND=local to auto-populate the library.",
        )
        return 0

    ready_count = (
        await db.execute(select(func.count()).select_from(Document).where(Document.status == "ready"))
    ).scalar_one()
    if ready_count >= len(SEED_DOCS):
        return 0

    added = 0
    for spec in SEED_DOCS:
        if await seed_one_document(db, spec):
            added += 1
    if added:
        log.info("seed_corpus_ready", added=added, total=len(SEED_DOCS))
    return added
