"""Make an imported document behave like one of our own graded texts.

An imported web story arrives as bare prose: often no CEFR level (the admin
left the field blank) and never a glossary, so the Reader shows it with an
empty vocabulary panel while a seeded story shows cards. This closes that gap
by adding OUR learning scaffolding around the fetched text:

  * a CEFR level, if none was supplied — taken from the page's own labelling
    when it states one ("A1" in the title is a strong signal), otherwise
    judged from the text;
  * a `## Glossar` section of the hardest words, which is exactly what
    `reader-content.ts` parses into level-correct vocabulary cards.

What it deliberately does NOT do is rewrite, translate or re-title the source
prose. The body stays as fetched and `source_url` keeps pointing at the
original — this is annotation for private study, not republishing. Anything
you intend to serve publicly still needs the licence/attribution treatment in
`app/content/catalogue.py`.

Enrichment is best-effort: a failure leaves the document exactly as ingested.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document

log = structlog.get_logger(__name__)

CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1")

# ── Word lists vs prose ───────────────────────────────────────────────────────
# A vocabulary PDF ("1. sein to be ہونا होना hona") is a TABLE that lost its
# columns on extraction. Rendered as prose in the Reader it is unreadable, so
# the document is tagged and the client draws it back as a table.

# Numbered entry: "12. kennen to know <urdu> <hindi> janana"
_WORDLIST_ROW = re.compile(r"^\s*(\d{1,4})[.)]\s+(.+)$")
# Non-Latin script runs, used to split the columns back apart.
_ARABIC = r"؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿"
_DEVANAGARI = r"ऀ-ॿ"
_SCRIPT_SPLIT = re.compile(
    rf"^(?P<latin>[^{_ARABIC}{_DEVANAGARI}]+?)\s*"
    rf"(?P<urdu>[{_ARABIC}][{_ARABIC}\s]*)?\s*"
    rf"(?P<hindi>[{_DEVANAGARI}][{_DEVANAGARI}\s]*)?\s*"
    rf"(?P<roman>[A-Za-z][A-Za-z\s'-]*)?$"
)
# German multi-word verbs start with a reflexive pronoun; everything after the
# headword is the gloss.
_REFLEXIVE = ("sich",)
WORDLIST_MIN_ROWS = 12  # below this it's prose that happens to have a list in it
# 8-14 entries: enough to be useful on a story, few enough to read in the
# Reader's side panel without scrolling forever.
GLOSSARY_MIN, GLOSSARY_MAX = 8, 14
# Judging a level needs a sample, not the whole text — and the prompt is
# cheaper for it.
_SAMPLE_CHARS = 2500

# "(A1)", "A1-Niveau", "level B2" — publishers of graded readers almost always
# say the level out loud, and their own labelling beats our guess.
_LEVEL_IN_TEXT = re.compile(r"\b(A1|A2|B1|B2|C1|C2)\b")

_ENRICH_PROMPT = """You annotate graded {language_name} reading material for learners.

Given the text below, return ONLY a JSON object:
{{
  "cefr_level": "A1|A2|B1|B2|C1",
  "glossary": [{{"word": "...", "gloss_en": "short English meaning"}}]
}}

Rules:
- cefr_level: judge the TEXT's difficulty (vocabulary, tense range, sentence
  length), not the topic.
- glossary: {min_items}-{max_items} of the words a learner at that level would
  most likely need to look up. Use the dictionary form (nouns WITH their
  article, verbs in the infinitive). Skip words a beginner already knows."""


def level_from_label(*candidates: str | None) -> str | None:
    """A CEFR level the source itself declares, e.g. "… (A1) | MeloLingua"."""
    for text in candidates:
        if not text:
            continue
        match = _LEVEL_IN_TEXT.search(text)
        if match:
            level = match.group(1)
            # We teach A1–C1; treat a C2 label as our top band.
            return "C1" if level == "C2" else level
    return None


# Salvage pattern for a truncated response: one complete {"word", "gloss_en"}
# pair. A long glossary is exactly the shape that gets cut off at the token
# limit, and throwing away twelve good entries because the thirteenth was
# clipped mid-string is the wrong trade.
_ENTRY_RE = re.compile(
    r'"word"\s*:\s*"([^"]+)"\s*,\s*"gloss_en"\s*:\s*"([^"]+)"', re.S
)
_LEVEL_FIELD_RE = re.compile(r'"cefr_level"\s*:\s*"(A1|A2|B1|B2|C1)"', re.I)


def parse_enrichment(raw: str) -> dict[str, Any]:
    """Validate the model's JSON, salvaging a truncated response.

    Raises ValueError only when nothing usable can be recovered.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")

    data: dict[str, Any] | None = None
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            data = None  # fall through to salvage

    if data is not None:
        level = str(data.get("cefr_level") or "").upper()
        raw_entries = data.get("glossary") or []
    else:
        match = _LEVEL_FIELD_RE.search(text)
        level = (match.group(1).upper() if match else "")
        raw_entries = [
            {"word": w, "gloss_en": g} for w, g in _ENTRY_RE.findall(text)
        ]
        if not level and not raw_entries:
            raise ValueError("no JSON object found")

    if level not in CEFR_LEVELS:
        raise ValueError(f"bad cefr_level {level!r}")

    entries: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        gloss = str(item.get("gloss_en") or "").strip()
        if word and gloss:
            entries.append({"word": word, "gloss_en": gloss})
    return {"cefr_level": level, "glossary": entries[:GLOSSARY_MAX]}


def append_glossary(content: str, entries: list[dict[str, str]]) -> str:
    """Append the `## Glossar` section the Reader parses into vocab cards.

    Idempotent: a document that already carries a glossary is left alone, so
    re-ingesting never stacks duplicates.
    """
    if not entries or re.search(r"^#{1,4}\s*glossar\s*$", content, re.I | re.M):
        return content
    lines = [content.rstrip(), "", "## Glossar", ""]
    lines += [f"- **{e['word']}** — {e['gloss_en']}" for e in entries]
    return "\n".join(lines) + "\n"


async def enrich_document(db: AsyncSession, document: Document) -> bool:
    """Classify the document and add the scaffolding it's missing.

    Returns True if anything changed. Never raises: annotation is a bonus on
    top of an already-usable document.
    """
    content = (document.content_md or "").strip()
    if not content:
        return False

    # Classify FIRST — everything below branches on it, and the kind must be
    # stamped even when there is nothing else to add.
    kind = "wordlist" if looks_like_wordlist(content) else "prose"
    has_glossary = bool(re.search(r"^#{1,4}\s*glossar\s*$", content, re.I | re.M))
    # A word list IS a glossary; generating a 14-word one for a 500-entry verb
    # table would be both wasteful and wrong.
    wants_glossary = kind == "prose" and not has_glossary

    # The source's own label beats our judgement of a sample.
    level = document.cefr_level or level_from_label(document.title, content[:400])

    entries: list[dict[str, str]] = []
    if wants_glossary or not level:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.languages import target as target_language
        from app.ai.router import complete
        from app.ai.tasks import TaskType

        language_name = target_language(document.language or "de").name
        try:
            result = await complete(
                db,
                task_type=TaskType.CONTENT_GENERATE,
                messages=[
                    SystemMessage(
                        content=_ENRICH_PROMPT.format(
                            language_name=language_name,
                            min_items=GLOSSARY_MIN,
                            max_items=GLOSSARY_MAX,
                        )
                    ),
                    HumanMessage(content=content[:_SAMPLE_CHARS]),
                ],
                user_id=document.created_by,
            )
            parsed = parse_enrichment(result.text or "")
            level = level or parsed["cefr_level"]
            if wants_glossary:
                entries = parsed["glossary"]
        except Exception as exc:  # noqa: BLE001 — annotation is a bonus
            log.warning(
                "document_enrich_failed", document_id=str(document.id), error=str(exc)[:200]
            )

    changed = False
    if document.content_kind != kind:
        document.content_kind = kind
        changed = True
    if level and not document.cefr_level:
        document.cefr_level = level
        changed = True
    if entries:
        document.content_md = append_glossary(content, entries)
        changed = True
    # Imported prose is reading practice unless an admin said otherwise; a
    # word list is reference vocabulary, which is a different shelf.
    if not document.skill:
        document.skill = "vocabulary" if kind == "wordlist" else "reading"
        changed = True

    if changed:
        await db.commit()
        log.info(
            "document_enriched",
            document_id=str(document.id),
            kind=kind,
            cefr_level=document.cefr_level,
            glossary=len(entries),
        )
    return changed


def parse_wordlist_row(line: str) -> dict[str, str] | None:
    """One "12. kennen to know <urdu> <hindi> janana" line → its columns.

    Returns None for anything that isn't a numbered vocabulary entry, so a
    prose document that happens to contain "1. " can't be mistaken for a list.
    """
    numbered = _WORDLIST_ROW.match(line)
    if not numbered:
        return None
    index, rest = numbered.group(1), numbered.group(2).strip()

    parts = _SCRIPT_SPLIT.match(rest)
    if not parts:
        return None
    latin = (parts.group("latin") or "").strip()
    if not latin:
        return None

    # Split the Latin half into headword + gloss. The headword is one token
    # ("kennen") unless it's reflexive ("sich freuen").
    tokens = latin.split()
    if not tokens:
        return None
    take = 2 if tokens[0].lower() in _REFLEXIVE and len(tokens) > 1 else 1
    term = " ".join(tokens[:take])
    gloss = " ".join(tokens[take:]).strip()

    row = {
        "index": index,
        "term": term,
        "gloss": gloss,
        "urdu": (parts.group("urdu") or "").strip(),
        "hindi": (parts.group("hindi") or "").strip(),
        "roman": (parts.group("roman") or "").strip(),
    }
    # A row with only a headword carries no teaching value — treat as prose.
    return row if (row["gloss"] or row["urdu"] or row["hindi"]) else None


def parse_wordlist(content: str) -> list[dict[str, str]]:
    """Every numbered vocabulary row in the document, in order."""
    rows = []
    for line in (content or "").splitlines():
        row = parse_wordlist_row(line)
        if row:
            rows.append(row)
    return rows


def looks_like_wordlist(content: str) -> bool:
    """True when the document is mostly a vocabulary table, not prose.

    Both conditions matter: enough rows to be a list at all, AND those rows
    dominating the text — a story with a twelve-item glossary at the end is
    still a story.
    """
    lines = [ln for ln in (content or "").splitlines() if ln.strip()]
    if len(lines) < WORDLIST_MIN_ROWS:
        return False
    rows = parse_wordlist(content)
    return len(rows) >= WORDLIST_MIN_ROWS and len(rows) >= 0.5 * len(lines)
