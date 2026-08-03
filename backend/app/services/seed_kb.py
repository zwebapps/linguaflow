"""Starter knowledge-base corpus — shared by CLI and local bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import select
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
    # Graded reading corpus — every level gets stories so the Reader's picker
    # has something to offer at the learner's own level. Each file carries a
    # `## Glossar` section the Reader parses into level-correct vocab cards.
    SeedDoc("im_supermarkt.md", "Im Supermarkt", "A1", "reading"),
    SeedDoc("meine_familie.md", "Meine Familie", "A1", "reading"),
    SeedDoc("die_reise_nach_berlin.md", "Die Reise nach Berlin", "A2", "reading"),
    SeedDoc("beim_arzt.md", "Beim Arzt", "A2", "reading"),
    SeedDoc("das_vorstellungsgespraech.md", "Das Vorstellungsgespräch", "B1", "reading"),
    SeedDoc("der_umzug.md", "Der Umzug", "B1", "reading"),
    SeedDoc("die_stadt_der_zukunft.md", "Die Stadt der Zukunft", "B2", "reading"),
    SeedDoc("die_kunst_des_zuhoerens.md", "Die Kunst des Zuhörens", "C1", "reading"),
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
        await db.execute(
            select(Document).where(
                Document.title == spec.title,
                Document.language == getattr(spec, "language", "de"),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("seed_kb_skip_existing", title=spec.title, status=existing.status)
        return False

    document = Document(
        title=spec.title,
        source_type="md",
        storage_path=str(path),
        language=getattr(spec, "language", "de"),
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
    if not (settings.is_local or settings.SEED_ON_BOOT):
        return 0
    if not embeddings_available():
        log.warning(
            "seed_corpus_skipped",
            reason=(
                "Set OPENROUTER_API_KEY or EMBEDDING_BACKEND=local "
                "to auto-populate the library."
            ),
        )
        return 0

    # Compare against the SEED titles, not a bare ready-count: user uploads
    # inflate the count, which used to stop newly added seed files from ever
    # being ingested on an existing install.
    seeded_titles = set(
        (
            await db.execute(
                select(Document.title).where(Document.title.in_([s.title for s in SEED_DOCS]))
            )
        ).scalars()
    )
    if all(s.title in seeded_titles for s in SEED_DOCS):
        return 0

    added = 0
    for spec in SEED_DOCS:
        if await seed_one_document(db, spec):
            added += 1
    if added:
        log.info("seed_corpus_ready", added=added, total=len(SEED_DOCS))
    return added
