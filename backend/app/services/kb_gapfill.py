"""Fill a knowledge-base gap: author + ingest a level-appropriate Lernpaket.

When retrieval finds nothing for a learning request ("erklär mir den Genitiv",
"words for cooking"), the tutor used to answer from bare model memory and the
gap stayed a gap — the next learner hit it too. This service closes the loop:
one structured LLM call authors a compact learning pack for the topic —
vocabulary, grammar example sentences, mini-articles and mini-stories — which
is composed into ONE markdown document and pushed through the normal ingestion
pipeline (chunked, embedded, searchable, readable in the Reader, glossary
included). The next question on that topic is grounded.

Bounds are hard requirements, not vibes: 5–10 items of EACH category. The
model is asked for the target counts and the validator clamps/rejects, so a
pack can never be a single thin paragraph pretending to be coverage.

Guard-rails, because this both spends money and writes to shared state:
  * per-user rate limit (bucket "gapfill") on top of the monthly AI quota;
  * dedupe on the document title — refilling the same topic returns the
    existing document instead of generating a twin;
  * topics are length-capped and scrubbed before they reach the prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import router as ai_router
from app.ai.prompts import scrub_untrusted
from app.ai.tasks import TaskType
from app.core.cache import enforce_rate_limit
from app.core.errors import UpstreamError, ValidationError
from app.db.models import Document

log = structlog.get_logger(__name__)

MIN_ITEMS = 5
MAX_ITEMS = 10
# Mini-texts, not essays: each article/story is a short graded read. The pack
# is meant to seed retrieval and give the Reader something, not to be a book.
TEXT_WORDS = "60-110"
MAX_TOPIC_CHARS = 120

_PACK_PROMPT = """You author graded {target_language} learning material.
Create a learning pack on the topic "{topic}" for a CEFR {cefr} learner.

Return ONLY a JSON object, no markdown fences, with exactly this shape:
{{
  "title": "short {target_language} title for the pack",
  "vocabulary": [{{"word": "...", "gloss_en": "...", "example": "one {cefr}-level sentence using it"}}],
  "grammar_sentences": [{{"sentence": "...", "note_en": "what it demonstrates, one short clause"}}],
  "articles": [{{"title": "...", "text": "{text_words} words, factual tone, {cefr} level"}}],
  "stories": [{{"title": "...", "text": "{text_words} words, narrative tone, {cefr} level"}}]
}}

Counts: {min_items}-{max_items} vocabulary items, {min_items}-{max_items} grammar sentences,
{min_items} articles and {min_items} stories. Everything in {target_language} except the
_en fields. All language STRICTLY at {cefr} level."""


@dataclass(slots=True)
class GapFillResult:
    document_id: str
    title: str
    created: bool  # False when the topic was already covered (dedupe hit)
    counts: dict[str, int] = field(default_factory=dict)


def _clamp_items(items: Any, *, what: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{what} is not a list")
    cleaned = [i for i in items if isinstance(i, dict)][:MAX_ITEMS]
    if len(cleaned) < MIN_ITEMS:
        raise ValueError(f"only {len(cleaned)} {what} (need at least {MIN_ITEMS})")
    return cleaned


def parse_pack(raw: str) -> dict[str, Any]:
    """Validate the model's JSON against the 5–10 bounds. Raises ValueError."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    data = json.loads(text[start : end + 1])
    return {
        "title": str(data.get("title") or "").strip(),
        "vocabulary": _clamp_items(data.get("vocabulary"), what="vocabulary items"),
        "grammar_sentences": _clamp_items(
            data.get("grammar_sentences"), what="grammar sentences"
        ),
        "articles": _clamp_items(data.get("articles"), what="articles"),
        "stories": _clamp_items(data.get("stories"), what="stories"),
    }


def compose_markdown(topic: str, cefr: str, pack: dict[str, Any]) -> str:
    """One readable, chunkable document. The heading structure matters:
    the chunker splits on headings, so each article/story becomes its own
    retrievable chunk, and the `## Glossar` section lights up the Reader's
    vocabulary cards for this text."""
    lines: list[str] = [f"# {pack['title'] or f'Lernpaket: {topic}'}", ""]
    lines += [f"Thema: {topic} · Niveau {cefr}", ""]

    lines += ["## Wortschatz", ""]
    for v in pack["vocabulary"]:
        word = str(v.get("word") or "").strip()
        example = str(v.get("example") or "").strip()
        if word:
            lines.append(f"- **{word}** — {example}")
    lines.append("")

    lines += ["## Grammatik: Beispielsätze", ""]
    for g in pack["grammar_sentences"]:
        sentence = str(g.get("sentence") or "").strip()
        note = str(g.get("note_en") or "").strip()
        if sentence:
            lines.append(f"- {sentence}" + (f"  *({note})*" if note else ""))
    lines.append("")

    for i, a in enumerate(pack["articles"], start=1):
        lines += [f"## Artikel {i}: {str(a.get('title') or '').strip()}", ""]
        lines += [str(a.get("text") or "").strip(), ""]

    for i, s in enumerate(pack["stories"], start=1):
        lines += [f"## Geschichte {i}: {str(s.get('title') or '').strip()}", ""]
        lines += [str(s.get("text") or "").strip(), ""]

    lines += ["## Glossar", ""]
    for v in pack["vocabulary"]:
        word = str(v.get("word") or "").strip()
        gloss = str(v.get("gloss_en") or "").strip()
        if word and gloss:
            lines.append(f"- **{word}** — {gloss}")
    lines.append("")

    return "\n".join(lines)


async def fill_content_gap(
    db: AsyncSession,
    *,
    topic: str,
    cefr: str,
    language: str,
    user_id: Any,
    target_language_name: str = "German",
) -> GapFillResult:
    """Generate + ingest a pack for `topic`. Idempotent per (topic, level)."""
    clean_topic, _ = scrub_untrusted(topic or "")
    clean_topic = clean_topic.strip()[:MAX_TOPIC_CHARS]
    if len(clean_topic) < 3:
        raise ValidationError("Give the topic a name (at least 3 characters).")
    if cefr not in {"A1", "A2", "B1", "B2", "C1"}:
        raise ValidationError("cefr must be one of A1, A2, B1, B2, C1.")

    doc_title = f"Lernpaket: {clean_topic} ({cefr})"

    existing = (
        await db.execute(
            select(Document).where(
                Document.title == doc_title, Document.language == language
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return GapFillResult(
            document_id=str(existing.id), title=doc_title, created=False
        )

    # This call costs real tokens; its own bucket keeps a chatty session from
    # authoring packs in a loop (the monthly quota still applies on top).
    await enforce_rate_limit(str(user_id), bucket="gapfill", limit=3)

    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = _PACK_PROMPT.format(
        topic=clean_topic,
        cefr=cefr,
        target_language=target_language_name,
        text_words=TEXT_WORDS,
        min_items=MIN_ITEMS,
        max_items=MAX_ITEMS,
    )
    result = await ai_router.complete(
        db,
        task_type=TaskType.CONVERSATION,
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content=f'Create the pack for "{clean_topic}" now.'),
        ],
        user_id=user_id,
    )
    try:
        pack = parse_pack(result.text or "")
    except (ValueError, TypeError) as exc:
        log.warning("gapfill_pack_invalid", topic=clean_topic, error=str(exc))
        raise UpstreamError(
            "The generated learning pack was malformed; nothing was added. Try again."
        ) from exc

    content = compose_markdown(clean_topic, cefr, pack)

    # Ingestion parses from a file path (same contract as admin uploads), so
    # the pack lands in the uploads dir — reingest and delete both keep working.
    import asyncio
    import uuid as uuid_mod
    from pathlib import Path

    upload_dir = Path("var/uploads")
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    dest = upload_dir / f"gapfill-{uuid_mod.uuid4().hex}.md"
    await asyncio.to_thread(dest.write_text, content, "utf-8")

    from app.rag.ingest import ingest_document

    document = Document(
        title=doc_title,
        source_type="md",
        storage_path=str(dest),
        language=language,
        cefr_level=cefr,
        skill="grammar" if "grammatik" in clean_topic.lower() else "reading",
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    await ingest_document(db, document.id)
    await db.refresh(document)

    if document.status != "ready":
        raise UpstreamError(
            f"The pack was generated but ingestion failed: {document.error}"
        )

    counts = {
        "vocabulary": len(pack["vocabulary"]),
        "grammar_sentences": len(pack["grammar_sentences"]),
        "articles": len(pack["articles"]),
        "stories": len(pack["stories"]),
    }
    log.info("gapfill_pack_ready", topic=clean_topic, cefr=cefr, **counts)
    return GapFillResult(
        document_id=str(document.id), title=doc_title, created=True, counts=counts
    )
