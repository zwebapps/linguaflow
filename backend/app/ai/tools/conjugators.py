"""Per-language conjugation dispatch.

## Why this exists

`conjugation.py` is a German engine with German tense names (`praesens`), a German
infinitive check (-en/-n) and a German irregular table. `conjugation_es.py` is the
same idea for Spanish, with Spanish tense names and Spanish rules. Neither can
serve the other, and neither should try — a single "universal" conjugator would be
a pile of per-language branches pretending to be one algorithm.

So the engines stay separate and this module answers one question: given the
language a learner is studying, which engine conjugates, and what may they ask for?

Without this the Spanish engine would be unreachable: the tool imported
`conjugation.conjugate` directly, so a Spanish learner asking to conjugate
`tener` got the German engine rejecting it as "not an -en/-n infinitive".

## Tense names are per language on purpose

A Spanish learner should see `preterito`, not `praeteritum`. Normalising to
abstract labels ("past_simple") would be a translation layer that teaches a
vocabulary no textbook uses, and the learner has to say the real word to their
teacher.

## Adding a language

Write the engine, add one `_ENGINES` entry, and enable it in `ai/languages.py`.
A language with no engine is NOT an error here — `supports()` returns False and
the caller tells the learner the truth, which is better than a made-up paradigm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.ai.tools import conjugation as _de
from app.ai.tools import conjugation_es as _es


class _Engine(Protocol):
    """What every language engine must expose. Structural, so engines never
    import this module and there is no inheritance to keep in step."""

    PERSONS: tuple[str, ...]

    def conjugate(self, verb: str, tense: Any = ...) -> Any: ...


@dataclass(frozen=True, slots=True)
class LanguageConjugator:
    language: str
    module: Any
    tenses: tuple[str, ...]
    default_tense: str
    # Shown to the learner when they ask for something the engine cannot do, so
    # the message names real tenses rather than saying "invalid".
    infinitive_hint: str


_ENGINES: dict[str, LanguageConjugator] = {
    "de": LanguageConjugator(
        language="de",
        module=_de,
        tenses=("praesens", "praeteritum", "perfekt", "futur1", "konjunktiv2", "imperativ"),
        default_tense="praesens",
        infinitive_hint="a German infinitive ends in -en or -n (sprechen, sammeln)",
    ),
    "es": LanguageConjugator(
        language="es",
        module=_es,
        tenses=(
            "presente",
            "preterito",
            "imperfecto",
            "futuro",
            "condicional",
            "subjuntivo_presente",
        ),
        default_tense="presente",
        infinitive_hint="a Spanish infinitive ends in -ar, -er or -ir (hablar, comer, vivir)",
    ),
}


def supports(language: str) -> bool:
    """True when a RULE ENGINE can answer, not merely when we know the language.

    The distinction matters: the tutor may still discuss a language it cannot
    conjugate deterministically, but it must not present a generated paradigm as
    computed fact.
    """
    return (language or "").lower() in _ENGINES


def for_language(language: str) -> LanguageConjugator | None:
    return _ENGINES.get((language or "").lower())


def tenses_for(language: str) -> tuple[str, ...]:
    eng = for_language(language)
    return eng.tenses if eng else ()


def conjugate(language: str, verb: str, tense: str | None = None) -> dict[str, Any]:
    """Conjugate `verb` in the engine for `language`.

    Raises `ValueError` for an unsupported language or tense — the caller turns
    that into a sentence for the learner. Deliberately NOT falling back to
    another language's engine: a German paradigm for a Spanish verb is worse than
    an honest "I can't do that yet", because the learner cannot tell it is wrong.
    """
    eng = for_language(language)
    if eng is None:
        raise ValueError(
            f"No deterministic conjugator for {language!r}. "
            f"Supported: {', '.join(sorted(_ENGINES))}."
        )
    chosen = (tense or eng.default_tense).lower()
    if chosen not in eng.tenses:
        raise ValueError(
            f"{chosen!r} is not a tense this engine knows for {language!r}. "
            f"Try one of: {', '.join(eng.tenses)}."
        )
    return dict(eng.module.conjugate(verb, chosen))


def persons_for(language: str) -> tuple[str, ...]:
    eng = for_language(language)
    return tuple(eng.module.PERSONS) if eng else ()
