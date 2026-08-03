"""Knowledge-base gap filling — the Lernpaket generator.

What's worth pinning: the 5–10 bounds are a CONTRACT (a pack with two words is
not coverage, and fifty mini-articles is a runaway bill), the markdown
composition must produce the heading structure the chunker and the Reader's
glossary parser rely on, and a malformed model response must reject cleanly
rather than ingest garbage. All hermetic — no LLM, no DB.
"""

from __future__ import annotations

import json

import pytest

from app.services import kb_gapfill as gf


def _pack_json(n_vocab=6, n_gram=5, n_art=5, n_story=5) -> str:
    return json.dumps(
        {
            "title": "Lernpaket: Im Restaurant",
            "vocabulary": [
                {"word": f"das Wort{i}", "gloss_en": f"word {i}", "example": f"Satz {i}."}
                for i in range(n_vocab)
            ],
            "grammar_sentences": [
                {"sentence": f"Ich esse gern Nummer {i}.", "note_en": "present tense"}
                for i in range(n_gram)
            ],
            "articles": [
                {"title": f"Artikel {i}", "text": "Text. " * 30} for i in range(n_art)
            ],
            "stories": [
                {"title": f"Geschichte {i}", "text": "Es war einmal. " * 15}
                for i in range(n_story)
            ],
        }
    )


# ── parse_pack: the 5–10 contract ─────────────────────────────────────────────


def test_a_valid_pack_parses_with_all_categories() -> None:
    pack = gf.parse_pack(_pack_json())
    assert len(pack["vocabulary"]) == 6
    assert len(pack["grammar_sentences"]) == 5
    assert len(pack["articles"]) == 5
    assert len(pack["stories"]) == 5


def test_too_few_items_is_rejected_not_padded() -> None:
    """Four words is not a learning pack. Reject; the caller reports failure."""
    with pytest.raises(ValueError, match="vocabulary"):
        gf.parse_pack(_pack_json(n_vocab=4))


def test_too_many_items_are_clamped_to_the_cap() -> None:
    """The model over-delivering must cap the bill, not grow the document."""
    pack = gf.parse_pack(_pack_json(n_vocab=25))
    assert len(pack["vocabulary"]) == gf.MAX_ITEMS


def test_markdown_fences_are_tolerated() -> None:
    fenced = "```json\n" + _pack_json() + "\n```"
    assert gf.parse_pack(fenced)["title"].startswith("Lernpaket")


def test_garbage_is_rejected() -> None:
    with pytest.raises(ValueError):
        gf.parse_pack("Sorry, I cannot help with that.")


# ── compose_markdown: the structure downstream code relies on ────────────────


def test_composed_document_has_the_load_bearing_sections() -> None:
    pack = gf.parse_pack(_pack_json())
    md = gf.compose_markdown("Im Restaurant", "A2", pack)
    # Headings drive chunk boundaries…
    assert "## Wortschatz" in md
    assert "## Grammatik: Beispielsätze" in md
    assert "## Artikel 1:" in md and "## Geschichte 5:" in md
    # …and the trailing Glossar section is what the Reader parses into
    # level-correct vocabulary cards (same convention as the seed stories).
    assert md.rstrip().split("## ")[-1].startswith("Glossar")
    assert "- **das Wort0** — word 0" in md


def test_every_vocabulary_item_reaches_the_glossary() -> None:
    pack = gf.parse_pack(_pack_json(n_vocab=8))
    md = gf.compose_markdown("Essen", "A1", pack)
    glossar = md.split("## Glossar")[1]
    assert glossar.count("- **") == 8
