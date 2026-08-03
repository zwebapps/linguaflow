"""Learning materials catalogue.

The tests worth having here are the LICENCE ones. Everything in this catalogue is
someone else's work served under terms, and half of it is CC BY-SA where credit is
a condition of use rather than a courtesy. A missing attribution string is not a
cosmetic bug — it is a breach, and it is invisible until someone complains.

The rest guard the two things that make a materials page feel broken: a language
pack that ships vocabulary but no reading, and a level filter that hides material
which legitimately spans levels.
"""

from __future__ import annotations

import pytest

from app.ai.languages import TARGET_LANGUAGES
from app.content import catalogue as cat
from app.content import frequency, gutenberg

# ── Licence integrity ─────────────────────────────────────────────────────────


def test_every_material_declares_a_known_licence() -> None:
    """No free-text licences.

    `LICENCES` is a closed set so that adding one is a decision with a name and a
    URL, rather than a string somebody typed once and nobody checked.
    """
    for m in cat.CATALOGUE:
        assert m.licence in cat.LICENCES, f"{m.id} cites an unknown licence {m.licence!r}"


def test_attribution_is_present_wherever_the_licence_demands_it() -> None:
    """CC BY and CC BY-SA both require credit. An empty string is a breach."""
    for m in cat.CATALOGUE:
        if m.licence_info.requires_attribution:
            assert m.attribution.strip(), f"{m.id} is {m.licence} but credits nobody"


def test_no_all_rights_reserved_material_sneaks_in() -> None:
    """Only redistributable sources.

    Linking a learner to a pirated textbook PDF would be worse than linking
    nothing — it is the kind of thing that gets a product removed.
    """
    allowed = {"public-domain", "cc-by-sa-4.0", "cc-by-2.0-fr"}
    assert {m.licence for m in cat.CATALOGUE} <= allowed


def test_share_alike_is_flagged_so_the_ui_can_say_so() -> None:
    """A learner redistributing CC BY-SA work inherits the obligation."""
    assert cat.LICENCES["cc-by-sa-4.0"].share_alike is True
    assert cat.LICENCES["public-domain"].share_alike is False
    assert cat.LICENCES["public-domain"].requires_attribution is False


def test_every_url_is_https() -> None:
    """These are fetched server-side and shown to learners; plain HTTP is not on."""
    for m in cat.CATALOGUE:
        assert m.url.startswith("https://"), f"{m.id} is not https"


# ── Catalogue shape ───────────────────────────────────────────────────────────


def test_material_ids_are_unique() -> None:
    ids = [m.id for m in cat.CATALOGUE]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("lang", ["de", "es", "fr", "it"])
def test_each_language_gets_a_complete_pack(lang: str) -> None:
    """Vocabulary, grammar, books AND sentences.

    A language with words but nothing to read, or reading but no grammar notes,
    is the asymmetry that makes a course feel half-finished.
    """
    kinds = {m.kind for m in cat.materials_for(lang)}
    assert kinds == {"vocabulary", "grammar", "book", "sentences"}


def test_the_catalogue_only_covers_languages_the_registry_knows() -> None:
    """Materials for a language the platform has never heard of would be orphaned."""
    for code in cat.languages_with_materials():
        assert code in TARGET_LANGUAGES


def test_languages_are_returned_in_a_stable_order() -> None:
    """An endpoint whose ordering shifts between calls makes for flaky clients."""
    assert cat.languages_with_materials() == sorted(cat.languages_with_materials())


def test_filtering_by_level_keeps_material_that_spans_levels() -> None:
    """A frequency list covers A1 upward by construction.

    Hiding it from a B1 learner because it carries no single `cefr_level` would be
    a filter doing the opposite of its job.
    """
    spanning = [m for m in cat.materials_for("de", cefr_level="B1") if m.cefr_level is None]
    assert spanning, "level filtering dropped everything that spans levels"


def test_find_returns_none_for_an_unknown_id() -> None:
    assert cat.find("de-frequency-50k") is not None
    assert cat.find("nope") is None


# ── Frequency lists ───────────────────────────────────────────────────────────


def _synthetic_list(n: int) -> str:
    """`n` digit-free words, descending in count.

    Digit-free on purpose: the parser rejects any token containing a digit, so
    "wort0" would be filtered as corpus noise and the fixture would test nothing.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    words = []
    for i in range(n):
        a, b = divmod(i, len(alphabet))
        words.append(f"{alphabet[a % len(alphabet)]}{alphabet[b]}wort")
    return "\n".join(f"{w} {100000 - i}" for i, w in enumerate(words))


def test_frequency_parsing_ranks_and_bands() -> None:
    text = _synthetic_list(600)
    entries = frequency.parse(text, "de")
    assert entries[0].rank == 1
    assert entries[0].cefr_level == "A1"
    # 501st surviving word crosses out of the A1 band.
    assert entries[500].cefr_level == "A2"


def test_frequency_parsing_drops_corpus_noise() -> None:
    """Subtitle corpora are dirty. A learner's first flashcard must not be "1"."""
    text = "der 100\n1 99\n42 98\nhaus 97\n_ 96"
    words = [e.word for e in frequency.parse(text, "de")]
    assert words == ["der", "haus"]


def test_ranks_are_contiguous_after_filtering() -> None:
    """Dropping noise must not leave gaps, or "the first 500" stops meaning that."""
    text = "der 100\n1 99\nhaus 98\n42 97\nund 96"
    entries = frequency.parse(text, "de")
    assert [e.rank for e in entries] == [1, 2, 3]


def test_real_one_letter_words_survive_per_language() -> None:
    """Spanish "y" and "o" are among its commonest words; German has none."""
    assert [e.word for e in frequency.parse("y 100\no 99", "es")] == ["y", "o"]
    assert frequency.parse("y 100", "de") == []


def test_accented_words_are_kept() -> None:
    """A filter that strips ä/ç/ñ/ß would gut every language here."""
    text = "größe 100\nniño 99\nêtre 98"
    assert len(frequency.parse(text, "de")) == 3


def test_malformed_lines_do_not_deny_the_learner_the_rest() -> None:
    text = "der 100\ngarbage\nhaus notanumber\nund 97"
    assert [e.word for e in frequency.parse(text, "de")] == ["der", "und"]


def test_band_for_returns_none_past_the_last_band() -> None:
    assert frequency.band_for(1) == "A1"
    assert frequency.band_for(10_000) == "C1"
    # The long tail is of no use to a learner and is deliberately dropped.
    assert frequency.band_for(10_001) is None


# ── Gutenberg ─────────────────────────────────────────────────────────────────


def _payload(formats: dict[str, str]) -> dict:
    return {
        "results": [
            {
                "id": 2000,
                "title": "  Faust  ",
                "authors": [{"name": "Goethe, Johann Wolfgang von"}],
                "formats": formats,
                "subjects": ["Drama", "German literature"],
                "download_count": 5000,
            }
        ]
    }


def test_plain_text_is_preferred_over_epub() -> None:
    """Both parse, but plain text needs no unzipping and chunks predictably."""
    books = gutenberg.parse_books(
        _payload(
            {
                "application/epub+zip": "https://x/f.epub",
                "text/plain; charset=utf-8": "https://x/f.txt",
            }
        ),
        "de",
    )
    assert books[0].download_url.endswith(".txt")
    assert books[0].source_type == "txt"


def test_epub_is_used_when_there_is_no_plain_text() -> None:
    books = gutenberg.parse_books(_payload({"application/epub+zip": "https://x/f.epub"}), "de")
    assert books[0].source_type == "epub"


def test_zip_links_are_rejected_even_when_the_mime_matches() -> None:
    """The pipeline expects a document, not an archive."""
    assert gutenberg.parse_books(_payload({"text/plain": "https://x/f.zip"}), "de") == []


def test_books_with_no_usable_format_are_dropped() -> None:
    """A catalogue row whose download link fails is worse than one fewer book."""
    assert gutenberg.parse_books(_payload({"image/jpeg": "https://x/cover.jpg"}), "de") == []


def test_titles_are_trimmed_and_bylines_readable() -> None:
    book = gutenberg.parse_books(_payload({"text/plain": "https://x/f.txt"}), "de")[0]
    assert book.title == "Faust"
    assert book.byline == "Goethe, Johann Wolfgang von"


def test_an_anonymous_work_still_gets_a_byline() -> None:
    payload = _payload({"text/plain": "https://x/f.txt"})
    payload["results"][0]["authors"] = []
    assert gutenberg.parse_books(payload, "de")[0].byline == "Unknown author"


def test_an_empty_or_odd_payload_yields_no_books_rather_than_raising() -> None:
    for payload in ({}, {"results": None}, {"results": []}):
        assert gutenberg.parse_books(payload, "de") == []


# ── Route ordering ────────────────────────────────────────────────────────────


def test_literal_routes_are_declared_before_the_catch_all() -> None:
    """`/{material_id}` must not shadow `/books` and `/languages`.

    FastAPI matches in declaration order, so a catch-all declared first would
    swallow both sibling routes and they would 404 with "No such material" —
    a confusing failure that looks like missing data rather than a routing bug.
    Reordering the functions in the module is all it would take to break this.
    """
    from app.api.v1 import materials

    order = [r.path for r in materials.router.routes]  # type: ignore[attr-defined]
    catch_all = order.index("/{material_id}")
    assert order.index("/books") < catch_all
    assert order.index("/languages") < catch_all
