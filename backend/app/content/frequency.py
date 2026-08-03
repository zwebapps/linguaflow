"""Starter vocabulary from a frequency list.

Turns `{word} {count}` lines into a CEFR-banded starter deck, so a learner who
picks up a new language has something to review on day one instead of an empty
deck they have to fill by hand.

## Why frequency, and why band it

Frequency order is the closest cheap proxy for usefulness: the first few hundred
words of a subtitle corpus are the words a learner will actually hear. Bands are
a presentation choice — A1 is "the first 500", not a claim about the CEFR
descriptors, and the docstring on `BANDS` says so rather than implying the
Council of Europe ranked these words.

## What is filtered out and why

Subtitle corpora are dirty: they carry numerals, single letters, stage
directions, and fragments of the source language's markup. Left in, a learner's
first flashcard session is "1", "ah", "hm" — which reads as a broken product.
The filter is deliberately conservative: it drops what is clearly not a word
rather than trying to guess parts of speech, which needs a lemmatiser per
language and is the job of the dictionary tool, not this loader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)

# Cumulative rank ceilings. A1 = the first 500 words by frequency, and so on.
# These are BANDS OF A FREQUENCY LIST, not CEFR vocabulary specifications — the
# real CEFR descriptors are about what a learner can do, not a word count. The
# mapping is a useful ordering for a starter deck and nothing more.
BANDS: list[tuple[str, int]] = [
    ("A1", 500),
    ("A2", 1500),
    ("B1", 3000),
    ("B2", 6000),
    ("C1", 10000),
]

# One capital-letter-or-not word, allowing internal hyphens and apostrophes
# (l'eau, Zeit-schrift) and any Unicode letter, so ä/ç/ñ/ß survive. No digits,
# no lone letters — a single letter is nearly always corpus noise, and the
# exceptions ("a", "y", "o", "e" as real words) are added back explicitly.
_WORD = re.compile(r"^[^\W\d_](?:[\w'’-]*[^\W\d_])?$", re.UNICODE)

# Real one-letter words worth keeping, per language. Dropping these would lose
# Spanish "y"/"o" and French "à"/"y", which are among the commonest words there.
_KEEP_SINGLE: dict[str, set[str]] = {
    "de": set(),
    "es": {"y", "o", "a", "e", "u"},
    "fr": {"a", "y", "à"},
    "it": {"e", "o", "a", "è"},
    "en": {"a", "i"},
}


@dataclass(frozen=True, slots=True)
class FrequencyEntry:
    rank: int
    word: str
    count: int
    cefr_level: str


def _is_wordlike(token: str, language: str) -> bool:
    if len(token) == 1:
        return token in _KEEP_SINGLE.get(language, set())
    return bool(_WORD.match(token))


def band_for(rank: int) -> str | None:
    """CEFR band for a 1-based frequency rank, or None past the last band."""
    for level, ceiling in BANDS:
        if rank <= ceiling:
            return level
    return None


def parse(text: str, language: str, *, limit: int | None = None) -> list[FrequencyEntry]:
    """Parse a FrequencyWords file into ranked, banded entries.

    Ranking is assigned AFTER filtering, so dropping noise does not leave gaps
    in the sequence — rank 1 is the commonest word we actually kept, which is
    what a learner's "first 500" should mean.

    Malformed lines are skipped rather than raising: these files are generated
    from crowd-sourced subtitles and a single bad line should not deny a learner
    the other 49,999.
    """
    out: list[FrequencyEntry] = []
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) != 2:
            continue
        word, count_s = parts
        try:
            count = int(count_s)
        except ValueError:
            continue
        if not _is_wordlike(word, language):
            continue
        rank = len(out) + 1
        level = band_for(rank)
        if level is None:
            break  # past C1; the tail is long and of no use to a learner
        out.append(FrequencyEntry(rank=rank, word=word, count=count, cefr_level=level))
        if limit is not None and len(out) >= limit:
            break
    return out


async def fetch(url: str, language: str, *, limit: int | None = None) -> list[FrequencyEntry]:
    """Download and parse a frequency list.

    Returns [] on any network or decode failure rather than raising: a starter
    deck is a nice-to-have at signup, and failing to fetch one must never block
    a learner from creating an account.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            res = await client.get(url)
            res.raise_for_status()
            # These files are UTF-8 but served without a charset, so httpx guesses
            # latin-1 and mangles every accent. Decode explicitly.
            text = res.content.decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("frequency_fetch_failed", url=url, error=str(exc))
        return []
    entries = parse(text, language, limit=limit)
    log.info("frequency_fetched", url=url, language=language, entries=len(entries))
    return entries
