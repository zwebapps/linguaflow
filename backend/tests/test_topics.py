"""Topic registry — the syllabus behind the "pick a topic and start" dropdowns.

The registry replaced free-text topics because free text broke two things:
learners had no menu of what their level covers, and `TopicStat` fragmented
("Dativ" / "dative case" / "Dative Case" as three weak spots). What is worth
pinning is therefore the *shape*: stable unique ids, every German level
actually populated, and both grammar and thematic entries at every level —
a level with structures to drill but nothing to talk about (or vice versa)
is the asymmetry that makes a course feel half-finished.
"""

from __future__ import annotations

import pytest

from app.content import topics as reg

# ── Registry shape ────────────────────────────────────────────────────────────


def test_topic_ids_are_unique() -> None:
    """Ids are the join key for quizzes and analytics; a duplicate is corruption."""
    ids = [t.id for t in reg.TOPICS]
    assert len(ids) == len(set(ids))


def test_every_topic_sits_at_a_real_cefr_level() -> None:
    for t in reg.TOPICS:
        assert t.level in reg.CEFR_LEVELS, f"{t.id} claims unknown level {t.level!r}"


@pytest.mark.parametrize("level", reg.CEFR_LEVELS)
def test_german_has_a_syllabus_at_every_level(level: str) -> None:
    """An empty dropdown at any level sends the learner back to guessing.

    Both kinds must be present: grammar to drill AND a theme to apply it to.
    """
    kinds = {t.kind for t in reg.topics_for("de", level)}
    assert kinds == {"grammar", "theme"}, f"German {level} is missing {({'grammar', 'theme'} - kinds)}"


def test_titles_are_bilingual() -> None:
    """`title` teaches the German name; `title_en` glosses it for beginners.

    An A1 learner cannot be handed „Wechselpräpositionen“ with no gloss.
    """
    for t in reg.TOPICS:
        assert t.title.strip() and t.title_en.strip(), f"{t.id} has a blank title"


# ── Lookup behaviour ──────────────────────────────────────────────────────────


def test_level_filter_narrows_to_exactly_that_level() -> None:
    a2 = reg.topics_for("de", "A2")
    assert a2 and all(t.level == "A2" for t in a2)


def test_unknown_language_is_empty_not_an_error() -> None:
    """No syllabus yet is a real state (fr/it aren't taught) — the client falls
    back to free-text entry, so the honest response is [] rather than a 500."""
    assert reg.topics_for("fr") == []


def test_unknown_level_is_a_caller_bug() -> None:
    """Silently returning everything would put C2 in an A1 dropdown."""
    with pytest.raises(ValueError):
        reg.topics_for("de", "C2")


def test_the_seed_corpus_topics_are_in_the_registry() -> None:
    """The seeded knowledge base covers Präsens/Dativ/Akkusativ-Präpositionen —
    the dropdown must offer the topics the corpus can actually ground."""
    ids = {t.id for t in reg.TOPICS}
    assert {"de-a1-praesens", "de-a2-dativ", "de-a2-akkusativ-praepositionen"} <= ids
