"""Splits parsed document text into retrievable chunks.

Strategy: split on markdown heading boundaries first (so a chunk never straddles
two unrelated sections), then pack each section's paragraphs to
`settings.CHUNK_TOKENS` with `settings.CHUNK_OVERLAP_TOKENS` overlap via
`RecursiveCharacterTextSplitter`. When the source carries page numbers (PDFs),
each page is processed independently so every chunk keeps a single, correct
`page` — packing across a page boundary would make that attribution a lie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

# German compounds run long, but so does English — 4 chars/token is the standard
# rough estimate (OpenAI's own rule of thumb) and holds up well enough for both;
# this is only used to size the splitter and to report an approximate token_count,
# never for anything that needs to be exact (billing goes through real usage
# accounting in app/ai/router.py).
_CHARS_PER_TOKEN = 4

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)


@dataclass(slots=True)
class ChunkDraft:
    ordinal: int
    text: str
    heading: str | None
    page: int | None
    token_count: int


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _split_by_headings(text: str) -> list[tuple[str | None, str]]:
    """Break `text` into (heading, body) sections on markdown `#`..`######` lines.

    The heading itself becomes each section's metadata, not part of its body —
    a chunk quoting "## Der Dativ" as body text would be a stranger citation than
    one carrying "Der Dativ" as its `heading` field.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append((None, preamble))

    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((heading, text[body_start:body_end]))

    return sections


def _make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_TOKENS * _CHARS_PER_TOKEN,
        chunk_overlap=settings.CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
    )


def chunk_text(text: str, *, pages: list[tuple[int, str]] | None = None) -> list[ChunkDraft]:
    """Produce sequential, non-empty `ChunkDraft`s from `text`.

    `pages`, if given, comes straight from `parsers.ParsedDoc.pages` — each
    `(page_number, page_text)` is chunked independently so page attribution
    stays accurate.
    """
    splitter = _make_splitter()
    units: list[tuple[int | None, str]] = list(pages) if pages else [(None, text)]

    drafts: list[ChunkDraft] = []
    for page_num, page_text in units:
        if not page_text or not page_text.strip():
            continue
        for heading, body in _split_by_headings(page_text):
            body = body.strip()
            if not body:
                continue
            for piece in splitter.split_text(body):
                piece = piece.strip()
                if not piece:
                    continue
                drafts.append(
                    ChunkDraft(
                        ordinal=len(drafts),
                        text=piece,
                        heading=heading,
                        page=page_num,
                        token_count=_estimate_tokens(piece),
                    )
                )

    return drafts
