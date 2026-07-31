"""The golden evaluation set for the RAG harness (see `runner.py`).

12 answerable German Q/A cases grounded in the seeded corpus — `seed/dativ.md`,
`seed/praesens.md`, `seed/akkusativ_praepositionen.md`, `seed/ein_tag_im_park.md`
— read in full before writing these so every question is actually answerable
from the text, plus 2 deliberately UNanswerable questions.

`relevant_doc_titles` uses the exact `Document.title` strings from
`scripts/seed_kb.py`'s `SEED_DOCS` (that's what ends up in the DB once these
files are ingested), so `runner.py` can compare retrieved-and-resolved titles
against this list directly.

The two unanswerable cases (genitive case, Berlin's population) are not
covered by any seeded document on purpose: they exist to catch confabulation.
A trustworthy RAG answer says it isn't sure rather than inventing a plausible-
sounding German grammar rule or fact that was never in the corpus — that's
what `expected_answer_contains` checks for on those two rows, and what
`runner.py`'s `faithfulness` judge is there to score.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class EvalCase:
    question: str
    expected_answer_contains: list[str]
    relevant_doc_titles: list[str]
    cefr_level: str


GOLDEN_SET: list[EvalCase] = [
    # ── Der Dativ ────────────────────────────────────────────────────────────
    EvalCase(
        question="Wie wird der Dativ auch genannt und mit welcher Frage findet man ihn?",
        expected_answer_contains=["Wem-Fall", "Wem"],
        relevant_doc_titles=["Der Dativ"],
        cefr_level="A2",
    ),
    EvalCase(
        question="Wie lautet der bestimmte Artikel im Dativ für ein maskulines Nomen wie 'Mann'?",
        expected_answer_contains=["dem Mann"],
        relevant_doc_titles=["Der Dativ"],
        cefr_level="A2",
    ),
    EvalCase(
        question="Nenne zwei Verben, die immer den Dativ verlangen.",
        expected_answer_contains=[
            "helfen", "danken", "gefallen", "gehören", "glauben", "folgen", "antworten",
        ],
        relevant_doc_titles=["Der Dativ"],
        cefr_level="A2",
    ),
    EvalCase(
        question="Welche Präpositionen verlangen immer den Dativ?",
        expected_answer_contains=["aus", "bei", "mit", "nach", "seit", "von", "zu"],
        relevant_doc_titles=["Der Dativ"],
        cefr_level="A2",
    ),
    EvalCase(
        question=(
            "Woran erkennt man bei den Wechselpräpositionen, ob Dativ oder "
            "Akkusativ verwendet wird?"
        ),
        expected_answer_contains=["Wo", "Wohin"],
        relevant_doc_titles=["Der Dativ"],
        cefr_level="B1",
    ),
    # ── Das Präsens ──────────────────────────────────────────────────────────
    EvalCase(
        question="Wie konjugiert man das Verb 'lernen' in der ich-Form im Präsens?",
        expected_answer_contains=["ich lerne"],
        relevant_doc_titles=["Das Präsens"],
        cefr_level="A1",
    ),
    EvalCase(
        question=(
            "Was passiert mit der Präsens-Endung, wenn der Verbstamm auf '-t' oder '-d' endet?"
        ),
        expected_answer_contains=["-e"],
        relevant_doc_titles=["Das Präsens"],
        cefr_level="A2",
    ),
    EvalCase(
        question="Wie lauten die Präsensformen von 'sein' für 'ich' und 'du'?",
        expected_answer_contains=["ich bin", "du bist"],
        relevant_doc_titles=["Das Präsens"],
        cefr_level="A1",
    ),
    EvalCase(
        question="Wie ändert sich der Stammvokal von 'fahren' in der du-Form im Präsens?",
        expected_answer_contains=["fährst"],
        relevant_doc_titles=["Das Präsens"],
        cefr_level="A2",
    ),
    # ── Präpositionen mit Akkusativ ──────────────────────────────────────────
    EvalCase(
        question="Welche Präpositionen verlangen immer den Akkusativ?",
        expected_answer_contains=["durch", "für", "gegen", "ohne", "um", "bis", "entlang"],
        relevant_doc_titles=["Präpositionen mit Akkusativ"],
        cefr_level="A2",
    ),
    EvalCase(
        question="Welcher Artikel ändert sich im Akkusativ gegenüber dem Nominativ?",
        expected_answer_contains=["maskulin", "den", "einen"],
        relevant_doc_titles=["Präpositionen mit Akkusativ"],
        cefr_level="A2",
    ),
    # ── Ein Tag im Park ──────────────────────────────────────────────────────
    EvalCase(
        question="Wie heißt der Hund, den Anna im Park trifft, und wann wacht Anna morgens auf?",
        expected_answer_contains=["Bruno", "sieben"],
        relevant_doc_titles=["Ein Tag im Park"],
        cefr_level="A1",
    ),
    # ── Deliberately unanswerable — nothing in the seeded corpus covers these.
    EvalCase(
        question="Wie dekliniert man Nomen im Genitiv, und wann verwendet man ihn?",
        expected_answer_contains=["nicht sicher", "weiß nicht", "kein"],
        relevant_doc_titles=[],
        cefr_level="B1",
    ),
    EvalCase(
        question="Wie viele Einwohner hat Berlin?",
        expected_answer_contains=["nicht sicher", "weiß nicht", "kein"],
        relevant_doc_titles=[],
        cefr_level="A2",
    ),
]
