"""Re-runs content-kind detection over every document already in the library.

`content_kind` is stamped at ingest time, so a document imported before a
detector existed keeps whatever it was classified as then — a verb chart
ingested last week is still filed as "prose" and shows up in the Reader as a
wall of columnless text instead of in Word lists.

Run: `python -m scripts.reclassify_docs [--dry-run]`. Idempotent; only writes
rows whose classification actually changed.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.logging import setup_logging
from app.db.models import Document
from app.db.session import SessionLocal
from app.services.doc_enrich import classify_content


async def _run(dry_run: bool) -> bool:
    changed: list[tuple[str, str, str]] = []
    async with SessionLocal() as db:
        documents = (await db.execute(select(Document))).scalars().all()
        for document in documents:
            kind = classify_content(document.content_md or "")
            if kind == document.content_kind:
                continue
            changed.append((document.title, document.content_kind, kind))
            if not dry_run:
                document.content_kind = kind
                # A chart is vocabulary to practise, not a text to read — the
                # skill drives which surfaces offer it.
                document.skill = "reading" if kind == "prose" else "vocabulary"
        if not dry_run:
            await db.commit()

    for title, before, after in changed:
        print(f"  {before:>9} → {after:<9} {title}")
    verb = "would change" if dry_run else "reclassified"
    print(f"{len(changed)} of {len(documents)} documents {verb}.")
    return True


def main() -> None:
    setup_logging()
    dry_run = "--dry-run" in sys.argv
    sys.exit(0 if asyncio.run(_run(dry_run)) else 1)


if __name__ == "__main__":
    main()
