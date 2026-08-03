"""Curated learning topics, per language and CEFR level.

## Why a fixed registry and not free text

Until now "topic" was whatever the learner typed into the quiz box, verbatim.
That has two costs. First, discoverability: an A1 learner staring at an empty
input has no idea what an A1 learner is supposed to study — the syllabus lived
in nobody's head but the model's. Second, analytics: `TopicStat` keys on the
raw string, so "Dativ", "dative case" and "Dative Case" accumulate as three
unrelated weak spots and the recommendations engine can never join them.

A registry fixes both: the UI renders a per-level dropdown ("pick a topic and
start"), and everything generated from a picked topic shares one canonical
title. Free text stays possible — the registry is the default path, not a wall.

## Shape

Topics are keyed by (language, level) and come in two kinds:

- ``grammar`` — a structure to drill (Der Dativ, Perfekt, Relativsätze…)
- ``theme``   — a situational/vocabulary field (Essen, Reisen, Bewerbung…)

Titles are in the TARGET language because that is what the learner is being
taught to recognise; ``title_en`` rides along so the UI can gloss for absolute
beginners. Only German is populated — DeutschFlow teaches German; the other
target languages in ``app.ai.languages`` are not `fully_supported` yet, and an
empty list here is the honest answer for them (the client falls back to free
text). Populate a language's syllabus when its course actually opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1")

TopicKind = Literal["grammar", "theme"]


@dataclass(frozen=True, slots=True)
class Topic:
    """One entry in a level's syllabus.

    ``id`` is the stable slug clients send back (quiz topic, analytics join key);
    ``title`` is the canonical display string that also feeds the generation
    prompt, so changing a title changes what the model is asked for — edit with
    that in mind.
    """

    id: str
    language: str
    level: str
    kind: TopicKind
    title: str
    title_en: str


def _de(level: str, kind: TopicKind, slug: str, title: str, title_en: str) -> Topic:
    return Topic(
        id=f"de-{level.lower()}-{slug}",
        language="de",
        level=level,
        kind=kind,
        title=title,
        title_en=title_en,
    )


# ── German syllabus (A1–C1) ───────────────────────────────────────────────────
# Sequenced loosely along the Goethe/telc curricula: what a course at that level
# actually drills, not an exhaustive grammar of German.

TOPICS: tuple[Topic, ...] = (
    # A1 — first structures + survival themes
    _de("A1", "grammar", "praesens", "Das Präsens", "Present tense"),
    _de("A1", "grammar", "artikel", "Artikel: der, die, das", "Articles: der, die, das"),
    _de("A1", "grammar", "sein-haben", "Die Verben „sein“ und „haben“", "The verbs 'sein' and 'haben'"),
    _de("A1", "grammar", "personalpronomen", "Personalpronomen", "Personal pronouns"),
    _de("A1", "grammar", "fragen", "W-Fragen und Ja/Nein-Fragen", "Questions: W-questions and yes/no"),
    _de("A1", "grammar", "plural", "Nomen und Plural", "Nouns and plural forms"),
    _de("A1", "grammar", "akkusativ", "Der Akkusativ", "The accusative case"),
    _de("A1", "grammar", "modalverben", "Modalverben: können, müssen, wollen", "Modal verbs: können, müssen, wollen"),
    _de("A1", "grammar", "trennbare-verben", "Trennbare Verben", "Separable verbs"),
    _de("A1", "theme", "sich-vorstellen", "Sich vorstellen", "Introducing yourself"),
    _de("A1", "theme", "familie", "Familie und Freunde", "Family and friends"),
    _de("A1", "theme", "essen-trinken", "Essen und Trinken", "Food and drink"),
    _de("A1", "theme", "einkaufen", "Einkaufen", "Shopping"),
    _de("A1", "theme", "tagesablauf", "Mein Tagesablauf", "My daily routine"),
    # A2 — cases in earnest, past tense, first subordinate clauses
    _de("A2", "grammar", "dativ", "Der Dativ", "The dative case"),
    _de("A2", "grammar", "akkusativ-praepositionen", "Präpositionen mit Akkusativ", "Prepositions with the accusative"),
    _de("A2", "grammar", "wechselpraepositionen", "Wechselpräpositionen", "Two-way prepositions"),
    _de("A2", "grammar", "perfekt", "Das Perfekt", "Present perfect tense"),
    _de("A2", "grammar", "komparativ", "Komparativ und Superlativ", "Comparative and superlative"),
    _de("A2", "grammar", "reflexive-verben", "Reflexive Verben", "Reflexive verbs"),
    _de("A2", "grammar", "nebensaetze-weil", "Nebensätze mit „weil“ und „dass“", "Subordinate clauses with 'weil' and 'dass'"),
    _de("A2", "grammar", "imperativ", "Der Imperativ", "The imperative"),
    _de("A2", "theme", "reisen", "Reisen und Verkehr", "Travel and transport"),
    _de("A2", "theme", "gesundheit", "Gesundheit und beim Arzt", "Health and at the doctor's"),
    _de("A2", "theme", "wohnen", "Wohnen und Wohnung", "Housing and home"),
    _de("A2", "theme", "arbeit", "Arbeit und Beruf", "Work and professions"),
    _de("A2", "theme", "wetter", "Wetter und Jahreszeiten", "Weather and seasons"),
    # B1 — the written-past / hypothetical / passive layer
    _de("B1", "grammar", "praeteritum", "Das Präteritum", "Simple past tense"),
    _de("B1", "grammar", "konjunktiv-2", "Konjunktiv II: Wünsche und höfliche Bitten", "Konjunktiv II: wishes and polite requests"),
    _de("B1", "grammar", "passiv", "Das Passiv (Präsens und Präteritum)", "Passive voice (present and past)"),
    _de("B1", "grammar", "relativsaetze", "Relativsätze", "Relative clauses"),
    _de("B1", "grammar", "genitiv", "Der Genitiv", "The genitive case"),
    _de("B1", "grammar", "infinitiv-zu", "Infinitiv mit „zu“", "Infinitive with 'zu'"),
    _de("B1", "grammar", "adjektivdeklination", "Adjektivdeklination", "Adjective declension"),
    _de("B1", "grammar", "plusquamperfekt", "Das Plusquamperfekt", "Past perfect tense"),
    _de("B1", "theme", "umwelt", "Umwelt und Natur", "Environment and nature"),
    _de("B1", "theme", "medien", "Medien und Internet", "Media and the internet"),
    _de("B1", "theme", "feste", "Feste und Traditionen", "Festivals and traditions"),
    _de("B1", "theme", "bewerbung", "Bewerbung und Lebenslauf", "Job applications and CVs"),
    # B2 — register, reported speech, nominal style
    _de("B2", "grammar", "passiv-alle-zeiten", "Das Passiv in allen Zeiten", "Passive voice in all tenses"),
    _de("B2", "grammar", "konjunktiv-1", "Konjunktiv I: indirekte Rede", "Konjunktiv I: reported speech"),
    _de("B2", "grammar", "nominalisierung", "Nominalisierung", "Nominalisation"),
    _de("B2", "grammar", "partizipialkonstruktionen", "Partizipialkonstruktionen", "Participle constructions"),
    _de("B2", "grammar", "modalverben-subjektiv", "Subjektive Bedeutung der Modalverben", "Subjective use of modal verbs"),
    _de("B2", "grammar", "konnektoren", "Konnektoren: obwohl, dennoch, folglich", "Connectors: obwohl, dennoch, folglich"),
    _de("B2", "grammar", "funktionsverbgefuege", "Feste Verb-Nomen-Verbindungen", "Fixed verb–noun collocations"),
    _de("B2", "theme", "wissenschaft", "Wissenschaft und Technik", "Science and technology"),
    _de("B2", "theme", "politik", "Politik und Gesellschaft", "Politics and society"),
    _de("B2", "theme", "kultur", "Kultur und Kunst", "Culture and art"),
    _de("B2", "theme", "wirtschaft", "Wirtschaft und Konsum", "Economy and consumption"),
    # C1 — style, idiom, discourse
    _de("C1", "grammar", "satzbau", "Komplexer Satzbau", "Complex sentence structure"),
    _de("C1", "grammar", "modalpartikeln", "Modalpartikeln: doch, ja, eben", "Modal particles: doch, ja, eben"),
    _de("C1", "grammar", "idiomatik", "Idiomatik und Redewendungen", "Idioms and set phrases"),
    _de("C1", "grammar", "stilmittel", "Stilistische Mittel", "Stylistic devices"),
    _de("C1", "grammar", "textkohaerenz", "Textkohärenz und Verweismittel", "Text cohesion and reference"),
    _de("C1", "theme", "philosophie", "Philosophie und Ethik", "Philosophy and ethics"),
    _de("C1", "theme", "literatur", "Literatur", "Literature"),
    _de("C1", "theme", "globalisierung", "Globalisierung", "Globalisation"),
    _de("C1", "theme", "fachdiskurs", "Beruflicher Fachdiskurs", "Professional discourse"),
)


def topics_for(language: str, level: str | None = None) -> list[Topic]:
    """Syllabus for a language, optionally narrowed to one CEFR level.

    Unknown language → empty list (the client falls back to free-text entry);
    unknown level is a caller bug and raises rather than silently returning
    everything.
    """
    lang = language.lower()
    if level is not None and level not in CEFR_LEVELS:
        raise ValueError(f"unknown CEFR level {level!r}")
    return [
        t
        for t in TOPICS
        if t.language == lang and (level is None or t.level == level)
    ]
