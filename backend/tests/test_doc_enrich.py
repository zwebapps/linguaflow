"""Imported documents get our learning scaffolding — title, level, glossary.

The bug behind these: a link import stored the URL as a placeholder title and
ingestion's `title or parsed.title` never replaced it, so the library listed
raw URLs as headings. And an imported story arrived with no level and no
glossary, so the Reader showed it with an empty vocabulary panel while a
seeded story showed cards.

Hermetic — no network, no model.
"""

from __future__ import annotations

import json

import pytest

from app.services import doc_enrich as enr

# ── The source's own level label beats our guess ──────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Auf dem Weihnachtsmarkt (A1) | MeloLingua", "A1"),
        ("Kurzgeschichte B2-Niveau", "B2"),
        ("German short story — level C1", "C1"),
        ("Ein Tag im Park", None),
    ],
)
def test_declared_level_is_detected(text: str, expected: str | None) -> None:
    assert enr.level_from_label(text) == expected


def test_c2_is_folded_into_our_top_band() -> None:
    """We teach A1–C1; a C2-labelled text belongs at the top, not nowhere."""
    assert enr.level_from_label("Sehr schwer (C2)") == "C1"


def test_first_label_wins_across_candidates() -> None:
    assert enr.level_from_label(None, "", "Story (A2)", "something B2") == "A2"


# ── Enrichment payload validation ─────────────────────────────────────────────


def _payload(level: str = "A1", n: int = 10) -> str:
    return json.dumps(
        {
            "cefr_level": level,
            "glossary": [
                {"word": f"das Wort{i}", "gloss_en": f"word {i}"} for i in range(n)
            ],
        }
    )


def test_valid_payload_parses() -> None:
    out = enr.parse_enrichment(_payload())
    assert out["cefr_level"] == "A1"
    assert len(out["glossary"]) == 10


def test_markdown_fences_are_tolerated() -> None:
    assert enr.parse_enrichment("```json\n" + _payload() + "\n```")["cefr_level"] == "A1"


def test_an_invalid_level_is_rejected() -> None:
    """A bogus level would land in a Document.cefr_level column the whole app
    filters on — reject rather than store garbage."""
    with pytest.raises(ValueError, match="cefr_level"):
        enr.parse_enrichment(_payload(level="B3"))


def test_glossary_is_capped() -> None:
    assert len(enr.parse_enrichment(_payload(n=40))["glossary"]) == enr.GLOSSARY_MAX


def test_malformed_entries_are_dropped_not_fatal() -> None:
    raw = json.dumps(
        {
            "cefr_level": "B1",
            "glossary": [
                {"word": "der Hund", "gloss_en": "dog"},
                {"word": "", "gloss_en": "empty word"},
                {"word": "die Katze"},  # no gloss
                "not a dict",
            ],
        }
    )
    assert enr.parse_enrichment(raw)["glossary"] == [{"word": "der Hund", "gloss_en": "dog"}]


def test_garbage_raises() -> None:
    with pytest.raises(ValueError):
        enr.parse_enrichment("I'm sorry, I can't help with that.")


# ── Glossary appending ────────────────────────────────────────────────────────


def test_glossary_uses_the_format_the_reader_parses() -> None:
    """`reader-content.ts` matches '- **word** — gloss' under a `## Glossar`
    heading; drift here silently empties the Reader's vocabulary panel."""
    out = enr.append_glossary(
        "Es war einmal…", [{"word": "der Markt", "gloss_en": "market"}]
    )
    assert "## Glossar" in out
    assert "- **der Markt** — market" in out


def test_appending_is_idempotent() -> None:
    """Re-ingesting a document must not stack a second glossary."""
    once = enr.append_glossary("Text", [{"word": "das Haus", "gloss_en": "house"}])
    twice = enr.append_glossary(once, [{"word": "der Baum", "gloss_en": "tree"}])
    assert twice == once
    assert twice.count("## Glossar") == 1


def test_no_entries_leaves_the_text_untouched() -> None:
    assert enr.append_glossary("Unverändert.", []) == "Unverändert."


def test_a_truncated_response_still_yields_its_complete_entries() -> None:
    """Models hit the token limit mid-glossary. Twelve good entries must not be
    thrown away because the thirteenth was clipped — this is the exact shape
    that came back from the live model on a real import."""
    truncated = (
        '{\n "cefr_level": "A1",\n "glossary": [\n'
        '  {"word": "der Weihnachtsmarkt", "gloss_en": "Christmas market"},\n'
        '  {"word": "das Lebkuchenherz", "gloss_en": "gingerbread heart"},\n'
        '  {"word": "zufrieden", "gloss_en"'  # ← cut off exactly here
    )
    out = enr.parse_enrichment(truncated)
    assert out["cefr_level"] == "A1"
    assert [e["word"] for e in out["glossary"]] == [
        "der Weihnachtsmarkt",
        "das Lebkuchenherz",
    ]
