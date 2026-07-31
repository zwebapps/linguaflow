"""Seeds the knowledge base with a small starter corpus.

Run: `python -m scripts.seed_kb`. Idempotent — a document is skipped by title if
it already exists. On local startup the API also calls `ensure_seed_corpus` so
learners see library content without this step.

Exits non-zero on any failure so it's safe to wire into a CI/CD smoke check.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.bootstrap import create_schema
from app.services.seed_kb import SEED_DOCS, embeddings_available, seed_one_document


async def _run() -> bool:
    if not embeddings_available():
        print(
            "OPENROUTER_API_KEY is not set — seeding needs it to generate embeddings "
            "(EMBEDDING_BACKEND=openrouter). Add it to backend/.env and retry, or set "
            "EMBEDDING_BACKEND=local to seed offline.",
            file=sys.stderr,
        )
        return False

    setup_logging()
    await create_schema()

    async with SessionLocal() as db:
        for spec in SEED_DOCS:
            await seed_one_document(db, spec)

    print(f"Seeded {len(SEED_DOCS)} knowledge-base document(s).")
    return True


def main() -> None:
    try:
        ok = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - top-level CLI: report and exit non-zero
        print(f"seed_kb failed: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
