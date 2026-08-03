"""Curated catalogue of learning materials, per language.

## Why a catalogue of POINTERS and not a folder of files

Every entry here is a URL plus its licence, never a copy of the text. Three
reasons, in order of how much they'd hurt to get wrong:

1. **Licence compliance is per-source.** Project Gutenberg is public domain;
   FrequencyWords is CC BY-SA 4.0; Tatoeba is CC BY 2.0 FR; Wikibooks is
   CC BY-SA 4.0. Share-alike terms travel with the text, and attribution has to
   reach the learner who reads it. A URL with a `licence` field beside it cannot
   drift apart from its terms; a checked-in .txt with the notice stripped can,
   and usually does.
2. **Repository weight.** A frequency list is ~1 MB per language and Gutenberg
   books run to megabytes each. Four languages of both would dominate the repo
   and every clone of it, to store something that is already hosted, versioned
   and mirrored elsewhere.
3. **Freshness.** Gutenberg gains texts; frequency lists get regenerated. A
   pointer picks that up; a copy silently rots.

The existing ingestion pipeline already parses pdf/docx/epub/md/txt/html, so an
entry becomes a real `Document` (chunked, embedded, searchable, readable in
Reading Mode) by being fetched — not by being special-cased.

## What is deliberately NOT here

No paid or all-rights-reserved material, however useful: no Goethe-Institut
workbooks, no Assimil, no Langenscheidt, no scanned textbooks. They cannot be
redistributed, and a "helpful" link to a pirated PDF is worse for a learner than
no link — it is the kind of thing that gets a product taken down.

## Adding a language

An entry needs a real licence and a URL that resolves. `LICENCES` is a closed
set on purpose: a new licence should be a considered decision with a name and a
URL, not a free-text string somebody typed once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── Licences we accept ────────────────────────────────────────────────────────

MaterialKind = Literal["vocabulary", "grammar", "reader", "book", "sentences"]


@dataclass(frozen=True, slots=True)
class Licence:
    """A licence we are willing to serve material under.

    `requires_attribution` and `share_alike` are not decoration — the API returns
    them so the UI can render the notice the licence actually demands, rather
    than a generic "source" link that satisfies nobody.
    """

    code: str
    name: str
    url: str
    requires_attribution: bool
    share_alike: bool


LICENCES: dict[str, Licence] = {
    "public-domain": Licence(
        "public-domain",
        "Public domain",
        "https://www.gutenberg.org/policy/permission.html",
        requires_attribution=False,
        share_alike=False,
    ),
    "cc-by-sa-4.0": Licence(
        "cc-by-sa-4.0",
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
        requires_attribution=True,
        share_alike=True,
    ),
    "cc-by-2.0-fr": Licence(
        "cc-by-2.0-fr",
        "CC BY 2.0 FR",
        "https://creativecommons.org/licenses/by/2.0/fr/",
        requires_attribution=True,
        share_alike=False,
    ),
}


# ── A material ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Material:
    """One thing a learner can study, and where it legally comes from."""

    id: str
    language: str
    kind: MaterialKind
    title: str
    description: str
    url: str
    licence: str
    # Who to credit. Required whenever the licence demands attribution —
    # enforced by a test, because an empty credit line is the single easiest way
    # to breach CC BY and the hardest to notice.
    attribution: str
    # None = spans levels (a frequency list covers A1 upward by construction).
    cefr_level: str | None = None
    # What the ingester should treat this as; None = not directly ingestible
    # (an index page, or something fetched through a dedicated client).
    source_type: str | None = None

    @property
    def licence_info(self) -> Licence:
        return LICENCES[self.licence]


# ── The catalogue ─────────────────────────────────────────────────────────────

# Frequency lists: the backbone of a starter deck. Ranked by how often a word
# appears in subtitle corpora, which is much closer to what a learner will
# actually hear than a dictionary's alphabetical order.
_FREQ_BASE = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018"
_FREQ_ATTRIB = "Hermit Dave, FrequencyWords (OpenSubtitles 2018)"

# Wikibooks course books — openly licensed grammar notes, and downloadable as
# PDF via the collection renderer, which is what makes them "PDF notes".
_WIKIBOOKS_ATTRIB = "Wikibooks contributors"

# Gutendex is a JSON API over Project Gutenberg. Listed per language as a
# QUERY, not as fixed book ids: the catalogue then keeps working as Gutenberg
# grows, and `content/gutenberg.py` turns it into concrete titles on demand.
_GUTENDEX = "https://gutendex.com/books?languages={lang}&sort=popular"


def _language_pack(lang: str, endonym: str, wikibook: str) -> list[Material]:
    """The four material types every supported language gets.

    Kept as one function so a new language cannot accidentally ship with
    vocabulary but no reading, or books but no grammar — the asymmetry that
    makes a course feel half-finished.
    """
    return [
        Material(
            id=f"{lang}-frequency-50k",
            language=lang,
            kind="vocabulary",
            title=f"{endonym}: 50,000 words by frequency",
            description=(
                "Ranked by how often each word appears in film and TV subtitles, so the "
                "earliest entries are the words you will hear first."
            ),
            url=f"{_FREQ_BASE}/{lang}/{lang}_50k.txt",
            licence="cc-by-sa-4.0",
            attribution=_FREQ_ATTRIB,
            source_type="txt",
        ),
        Material(
            id=f"{lang}-wikibooks-course",
            language=lang,
            kind="grammar",
            title=f"{endonym} grammar course (Wikibooks)",
            description=(
                "Community-written course notes covering grammar from beginner upward. "
                "Downloadable as PDF for offline study."
            ),
            url=wikibook,
            licence="cc-by-sa-4.0",
            attribution=_WIKIBOOKS_ATTRIB,
            source_type="html",
        ),
        Material(
            id=f"{lang}-gutenberg-popular",
            language=lang,
            kind="book",
            title=f"Public-domain books in {endonym}",
            description=(
                "Full-length works whose copyright has expired — free to read, download "
                "and keep. Sorted by popularity."
            ),
            url=_GUTENDEX.format(lang=lang),
            licence="public-domain",
            attribution="Project Gutenberg",
            # An API index, not a document: `content/gutenberg.py` expands it.
            source_type=None,
        ),
        Material(
            id=f"{lang}-tatoeba-sentences",
            language=lang,
            kind="sentences",
            title=f"{endonym} example sentences with translations",
            description=(
                "Human-translated sentence pairs — useful for seeing a word in context "
                "rather than in isolation."
            ),
            url=f"https://tatoeba.org/en/sentences/show_all_in/{lang}/none",
            licence="cc-by-2.0-fr",
            attribution="Tatoeba contributors",
            source_type=None,
        ),
    ]


# Only languages the platform can genuinely teach get a pack. Advertising
# materials for a language whose grammar engine does not exist would imply a
# course that is not there — the same mistake `ai/languages.py` avoids by
# keeping `fully_supported` conservative.
CATALOGUE: list[Material] = [
    *_language_pack("de", "Deutsch", "https://en.wikibooks.org/wiki/German"),
    *_language_pack("es", "Español", "https://en.wikibooks.org/wiki/Spanish"),
    *_language_pack("fr", "Français", "https://en.wikibooks.org/wiki/French"),
    *_language_pack("it", "Italiano", "https://en.wikibooks.org/wiki/Italian"),
]


def materials_for(
    language: str,
    *,
    kind: MaterialKind | None = None,
    cefr_level: str | None = None,
) -> list[Material]:
    """Catalogue entries for one language, optionally narrowed.

    Level filtering keeps entries with no level: a frequency list or a grammar
    course spans levels by construction, and hiding it from a B1 learner because
    it has no `cefr_level` would be a filter doing the opposite of its job.
    """
    out = [m for m in CATALOGUE if m.language == language]
    if kind is not None:
        out = [m for m in out if m.kind == kind]
    if cefr_level is not None:
        out = [m for m in out if m.cefr_level in (None, cefr_level)]
    return out


def languages_with_materials() -> list[str]:
    # Sorted so the API response order is stable — an endpoint whose ordering
    # shifts between calls makes for flaky clients and flaky tests.
    return sorted({m.language for m in CATALOGUE})


def find(material_id: str) -> Material | None:
    return next((m for m in CATALOGUE if m.id == material_id), None)
