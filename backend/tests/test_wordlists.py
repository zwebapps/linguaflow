"""The vocabulary shelf and its self-tests.

Two things are worth pinning here. The obvious one is that a test built from a
list must be answerable: exactly one correct option, distractors that are real
words from the same list. The less obvious one is that the answer key must
never be sent to the client — the question id is the TERM, and grading looks
the meaning up server-side, so a tampered payload can only change WHICH words
it is graded on, never what counts as correct.

Hermetic: `build_test` is pure and takes its own RNG, so these run without a
database, a model, or a network.
"""

from __future__ import annotations

import random

import pytest

from app.api.v1.wordlists import OPTIONS_PER_QUESTION, build_test
from app.core.errors import ValidationError

WORDS = [
    ("sein", "to be"),
    ("haben", "to have"),
    ("werden", "to become"),
    ("können", "can, to be able"),
    ("müssen", "must, to have to"),
    ("sagen", "to say"),
    ("machen", "to do, to make"),
    ("geben", "to give"),
    ("kommen", "to come"),
    ("wollen", "to want"),
]


def rows(pairs=WORDS) -> list[dict[str, str]]:
    return [
        {"index": str(i), "term": t, "gloss": g, "urdu": "", "hindi": "", "roman": ""}
        for i, (t, g) in enumerate(pairs, start=1)
    ]


def _rng() -> random.Random:
    # Seeded: a failure is reproducible instead of "it passed on my machine".
    return random.Random(42)


# ── Shape ─────────────────────────────────────────────────────────────────────


def test_builds_the_requested_number_of_questions() -> None:
    assert len(build_test(rows(), 6, _rng())) == 6


def test_never_asks_for_more_questions_than_the_list_has_words() -> None:
    """A 10-word list asked for 30 questions gives 10, not a crash or repeats."""
    out = build_test(rows(), 30, _rng())
    assert len(out) == len(WORDS)
    assert len({q["term"] for q in out}) == len(out)  # no word asked twice


def test_each_question_has_four_options_including_the_answer() -> None:
    for q in build_test(rows(), 5, _rng()):
        assert len(q["options"]) == OPTIONS_PER_QUESTION
        assert q["expected"] in q["options"]


def test_exactly_one_option_is_correct() -> None:
    """A duplicated correct answer would mark a right choice wrong."""
    for q in build_test(rows(), 8, _rng()):
        assert q["options"].count(q["expected"]) == 1
        assert len(set(q["options"])) == OPTIONS_PER_QUESTION


def test_distractors_are_real_words_from_the_same_list() -> None:
    """Plausible-by-construction beats a model inventing wrong answers."""
    known = {g for _, g in WORDS}
    for q in build_test(rows(), 8, _rng()):
        assert set(q["options"]) <= known


def test_the_question_id_is_the_term_so_no_key_is_sent() -> None:
    """The client echoes the term back; the server looks the meaning up. The
    response therefore carries no answer key at all."""
    for q in build_test(rows(), 5, _rng()):
        assert q["id"] == q["term"]


# ── Degenerate lists ──────────────────────────────────────────────────────────


def test_a_list_too_short_to_test_says_so() -> None:
    with pytest.raises(ValidationError, match="too short"):
        build_test(rows(WORDS[:3]), 5, _rng())


def test_entries_without_a_meaning_are_not_asked() -> None:
    """A row that lost its gloss during PDF extraction is unanswerable."""
    mixed = rows() + [
        {"index": "99", "term": "leer", "gloss": "", "urdu": "", "hindi": "", "roman": ""}
    ]
    assert all(q["term"] != "leer" for q in build_test(mixed, 11, _rng()))


def test_duplicate_terms_are_asked_only_once() -> None:
    """The term is the question id, so a repeated headword would collide."""
    dupes = rows() + [
        {"index": "11", "term": "sein", "gloss": "his", "urdu": "", "hindi": "", "roman": ""}
    ]
    terms = [q["term"] for q in build_test(dupes, 30, _rng())]
    assert terms.count("sein") == 1


def test_a_list_with_too_few_distinct_meanings_is_rejected() -> None:
    """Ten words that all mean "to go" can't produce four distinct options."""
    same = [(f"wort{i}", "to go") for i in range(10)]
    with pytest.raises(ValidationError, match="distinct"):
        build_test(rows(same), 5, _rng())


# ── Randomisation ─────────────────────────────────────────────────────────────


def test_two_tests_are_not_identical() -> None:
    """Practice should vary between attempts, or it becomes memorisation of
    option order rather than of vocabulary."""
    a = build_test(rows(), 5, random.Random(1))
    b = build_test(rows(), 5, random.Random(2))
    assert [q["term"] for q in a] != [q["term"] for q in b]


def test_the_same_seed_reproduces_the_same_test() -> None:
    a = build_test(rows(), 5, random.Random(7))
    b = build_test(rows(), 5, random.Random(7))
    assert [(q["term"], q["options"]) for q in a] == [(q["term"], q["options"]) for q in b]
