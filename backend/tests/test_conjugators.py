"""Per-language conjugation dispatch.

The bug this closes: the tool imported the German engine directly, so a Spanish
learner asking to conjugate `tener` was told it is not a valid -en/-n infinitive.
The Spanish engine existed and was unreachable.

The property that matters most here is the ABSENCE of a fallback. Handing a
Spanish verb to the German engine — or vice versa — would produce a paradigm that
looks authoritative and is nonsense, and the learner has no way to tell.
"""

from __future__ import annotations

import pytest

from app.ai.tools import conjugators


def test_each_language_routes_to_its_own_engine() -> None:
    assert conjugators.conjugate("de", "gehen", "praesens")["forms"]["ich"] == "gehe"
    assert conjugators.conjugate("es", "hablar", "presente")["forms"]["yo"] == "hablo"


def test_the_spanish_engine_is_actually_reachable() -> None:
    """The whole point: `tener` used to hit the German engine and be rejected."""
    out = conjugators.conjugate("es", "tener")
    assert out["forms"]["yo"] == "tengo"
    assert out["source"] == "rule_engine"


def test_each_language_uses_its_own_tense_names() -> None:
    """A Spanish learner should see `preterito`, not `praeteritum`.

    Normalising to abstract labels would teach a vocabulary no textbook uses.
    """
    assert "praeteritum" in conjugators.tenses_for("de")
    assert "preterito" in conjugators.tenses_for("es")
    assert "praeteritum" not in conjugators.tenses_for("es")


def test_a_tense_from_another_language_is_refused_not_translated() -> None:
    with pytest.raises(ValueError) as exc:
        conjugators.conjugate("es", "hablar", "praeteritum")
    # The message names what IS available, so the tutor can tell the learner.
    assert "preterito" in str(exc.value)


def test_there_is_no_cross_language_fallback() -> None:
    """A German paradigm for a Spanish verb is worse than admitting ignorance."""
    with pytest.raises(ValueError):
        conjugators.conjugate("it", "parlare")
    with pytest.raises(ValueError) as exc:
        conjugators.conjugate("xx", "whatever")
    # Lists the languages that DO work, rather than a bare failure.
    assert "de" in str(exc.value) and "es" in str(exc.value)


def test_omitting_the_tense_gives_each_languages_present() -> None:
    assert conjugators.conjugate("de", "gehen")["tense"] == "praesens"
    assert conjugators.conjugate("es", "hablar")["tense"] == "presente"


def test_supports_means_a_rule_engine_exists_not_merely_a_known_language() -> None:
    """The tutor may DISCUSS Italian; it must not present a computed paradigm."""
    assert conjugators.supports("de") is True
    assert conjugators.supports("es") is True
    assert conjugators.supports("it") is False
    assert conjugators.supports("") is False


def test_language_codes_are_case_insensitive() -> None:
    assert conjugators.supports("ES") is True
    assert conjugators.conjugate("DE", "gehen")["forms"]["ich"] == "gehe"


def test_persons_come_from_the_engine_not_a_shared_list() -> None:
    """German has `ich`; Spanish has `yo`. A shared list would fit neither."""
    assert "ich" in conjugators.persons_for("de")
    assert "yo" in conjugators.persons_for("es")
    assert conjugators.persons_for("it") == ()


def test_every_declared_tense_actually_works() -> None:
    """Guards the table drifting from the engines it points at.

    A tense listed here but unimplemented would reach the learner as a crash
    rather than a refusal.
    """
    for lang in ("de", "es"):
        verb = "gehen" if lang == "de" else "hablar"
        for tense in conjugators.tenses_for(lang):
            out = conjugators.conjugate(lang, verb, tense)
            assert out["forms"], f"{lang}/{tense} produced no forms"
