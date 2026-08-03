"""Public-domain books, per language, via Gutendex over Project Gutenberg.

Gutendex is a JSON API in front of Project Gutenberg's catalogue: no key, no
published rate limit, and every text is public domain, so a learner can read,
download and keep it.

## Why not store book ids in the catalogue

Because the catalogue would then need editing every time Gutenberg adds a text,
and it would silently rot when one is withdrawn. The catalogue stores a QUERY;
this module turns it into concrete titles at request time.

## Format choice

Each book offers several formats. We prefer `text/plain` over `epub`: the
ingestion pipeline parses both, but plain text needs no unzipping, has no
embedded images to fetch, and chunks predictably. EPUB is the fallback because
some texts have no plain-text rendering.

Gutenberg's plain-text files carry a long licence header and footer. Those are
stripped at ingestion, not here — this module reports what is available; the
parser decides what counts as content.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)

_GUTENDEX = "https://gutendex.com/books"

# Preference order. `text/plain; charset=utf-8` is the common exact key, but
# Gutenberg is inconsistent about the charset suffix, so matching is by prefix.
_FORMAT_PREFERENCE = ("text/plain", "application/epub+zip")

_SOURCE_TYPE_FOR = {"text/plain": "txt", "application/epub+zip": "epub"}

# Gutendex publishes no rate limit, but identifying the caller is basic courtesy
# to a free service and makes us reachable if we ever misbehave.
_UA = "LinguaFlow (language learning; contact support@linguaflow.dev)"


@dataclass(frozen=True, slots=True)
class Book:
    gutenberg_id: int
    title: str
    authors: list[str]
    language: str
    download_url: str
    # What the ingester should parse it as — matches `parsers.py`'s vocabulary.
    source_type: str
    subjects: list[str]
    download_count: int

    @property
    def byline(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown author"


def _pick_format(formats: dict[str, str]) -> tuple[str, str] | None:
    """(url, source_type) for the most ingestible format, or None.

    Skips `.zip` links even when the mime type matches: the pipeline expects a
    document, not an archive, and a zip would fail deep inside the parser rather
    than being rejected here where the reason is obvious.
    """
    for wanted in _FORMAT_PREFERENCE:
        for mime, url in formats.items():
            if mime.startswith(wanted) and not url.endswith(".zip"):
                return url, _SOURCE_TYPE_FOR[wanted]
    return None


def parse_books(payload: dict, language: str) -> list[Book]:
    """Map a Gutendex page to books we can actually ingest.

    Entries with no usable format are dropped rather than surfaced: a catalogue
    row whose download link does not work is worse than one fewer book.
    """
    out: list[Book] = []
    for item in payload.get("results") or []:
        chosen = _pick_format(item.get("formats") or {})
        if chosen is None:
            continue
        url, source_type = chosen
        out.append(
            Book(
                gutenberg_id=int(item.get("id", 0)),
                title=(item.get("title") or "Untitled").strip(),
                authors=[
                    a.get("name", "").strip()
                    for a in item.get("authors") or []
                    if a.get("name")
                ],
                language=language,
                download_url=url,
                source_type=source_type,
                subjects=list(item.get("subjects") or [])[:5],
                download_count=int(item.get("download_count") or 0),
            )
        )
    return out


async def popular(language: str, *, limit: int = 12) -> list[Book]:
    """Most-downloaded public-domain books in `language`.

    Returns [] on any failure rather than raising: the materials page should
    degrade to "no books right now" instead of erroring, since the vocabulary
    and grammar entries beside it are still perfectly usable.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            res = await client.get(
                _GUTENDEX,
                params={"languages": language, "sort": "popular"},
                headers={"user-agent": _UA},
            )
            res.raise_for_status()
            payload = res.json()
    except Exception as exc:
        log.warning("gutenberg_fetch_failed", language=language, error=str(exc))
        return []

    books = parse_books(payload, language)[:limit]
    log.info("gutenberg_fetched", language=language, books=len(books))
    return books
