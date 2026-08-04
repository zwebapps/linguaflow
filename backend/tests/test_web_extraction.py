"""Pulling a lesson out of a web page without the site wrapped around it.

Every case here is a real failure seen against a live graded-reader page. The
symptom a learner reported was cosmetic — a story that opened with a level
menu and "Your browser does not support the audio element." — but the same
extraction bug was also dropping the German text entirely and embedding
one-word fragments as if they were sentences.

Hermetic: these run the extractor over fixture HTML, never the network.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.rag.parsers import (
    _drop_boilerplate,
    _html_to_text,
    _main_content_html,
    _strip_chrome,
)

STORY = " ".join(["Es ist Dezember und Lukas schlendert über den Weihnachtsmarkt."] * 12)

PAGE = f"""
<html><body>
  <nav>Stories Level A1 (Beginner) A2 (Beginner) B1 (Mid-level) C1 (Advanced)</nav>
  <div class="crumbs">Home / German Short Stories / A1</div>
  <p>Heat wave in barcelona</p>
  <article class="teaser">Related: Ein Tag am See</article>
  <article class="main">
    <h1>Auf dem Weihnachtsmarkt</h1>
    <audio controls>Your browser does not support the audio element.</audio>
    <p>Click any word or sentence to get its translation.</p>
    <p>Überall erklingt fröhliche <button class="pop">Musik</button>.</p>
    <p>{STORY}</p>
  </article>
  <aside>Newsletter: subscribe for daily stories</aside>
  <footer>© MeloLingua</footer>
</body></html>
"""


def extract(html: str = PAGE) -> str:
    soup = _strip_chrome(BeautifulSoup(html, "lxml"))
    return _drop_boilerplate(_html_to_text(_main_content_html(soup) or ""))


# ── The furniture ─────────────────────────────────────────────────────────────


def test_the_level_menu_is_not_part_of_the_story() -> None:
    assert "A2 (Beginner)" not in extract()


def test_the_breadcrumb_trail_is_dropped() -> None:
    assert "German Short Stories" not in extract()


def test_the_audio_fallback_text_is_dropped() -> None:
    """It is only ever shown to browsers that can't play the clip — it is not
    something anyone reads, and it was appearing at the top of the story."""
    assert "does not support the audio element" not in extract().lower()


def test_the_readers_own_instructions_are_dropped() -> None:
    """"Click any word for a translation" is a caption on the site's own UI —
    inside the ingested story it reads as part of the text."""
    assert "Click any word" not in extract()


def test_the_sidebar_and_footer_go_too() -> None:
    text = extract()
    assert "Newsletter" not in text and "MeloLingua" not in text


# ── The content ───────────────────────────────────────────────────────────────


def test_the_story_itself_survives() -> None:
    assert "Lukas schlendert über den Weihnachtsmarkt" in extract()


def test_a_word_inside_a_button_is_kept() -> None:
    """On a graded reader the tappable vocabulary IS a button. Removing those
    elements deleted nouns out of the middle of sentences."""
    assert "fröhliche Musik." in extract()


def test_a_sentence_is_not_split_at_inline_markup() -> None:
    """One word per line isn't just ugly to read — the chunker would embed the
    fragments as if each were a sentence."""
    lines = extract().splitlines()
    assert "Musik" not in lines, "the tappable word became its own line"


def test_the_biggest_article_wins_over_a_teaser_card() -> None:
    """"Related stories" are <article> elements too."""
    text = extract()
    assert "Ein Tag am See" not in text
    assert "Auf dem Weihnachtsmarkt" in text


# ── Falling back ──────────────────────────────────────────────────────────────


def test_a_page_with_no_article_element_falls_back_to_readability() -> None:
    """<article>/<main> is a preference, not a requirement — plenty of pages
    use neither, and those must not come back empty."""
    from readability import Document as ReadabilityDocument

    plain = f"<html><body><div class='post'><p>{STORY}</p></div></body></html>"
    soup = _strip_chrome(BeautifulSoup(plain, "lxml"))
    assert _main_content_html(soup) is None  # nothing semantic to prefer

    fallback = ReadabilityDocument(str(soup)).summary(html_partial=True)
    assert "Lukas schlendert" in _html_to_text(fallback)


def test_a_teaser_sized_article_is_not_treated_as_the_page() -> None:
    """A stub <article> means the real text lives elsewhere; better to let
    readability score the page than to ingest a headline."""
    stub = "<html><body><article><h2>Coming soon</h2></article></body></html>"
    assert _main_content_html(_strip_chrome(BeautifulSoup(stub, "lxml"))) is None


# ── Not over-matching ─────────────────────────────────────────────────────────


def test_a_real_sentence_starting_with_home_is_kept() -> None:
    """The breadcrumb pattern needs a separator; "Home is where…" is prose."""
    assert _drop_boilerplate("Home is where the heart is.") == "Home is where the heart is."
