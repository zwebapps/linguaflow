"""Language registry — what the platform can teach, and in what.

## Why this exists

The product is German-first, but "German" was hardcoded in prompts, so even the
learner's own native language never reached the model. This module makes the pair
(*what you speak*, *what you're learning*) explicit data rather than an assumption
baked into a string.

## What is and isn't language-agnostic

Already generic, no work needed per language: RAG (chunk → embed → retrieve),
the tool-calling framework, SRS scheduling, quiz generation, writing evaluation,
CEFR levels (a Council of Europe framework covering many languages), auth,
analytics, A/B testing.

Genuinely language-specific, i.e. the real cost of adding a language:
`ai/tools/conjugation.py` (a German rule engine + irregular table),
`ai/tools/dictionary.py` (curated German words), `mcp/german_data.py`
(de.wiktionary / de.wikipedia / Tatoeba `deu`), the speaking scenarios, and the
seeded corpus. Those are **content**, not architecture — which is why a second
language is a bounded piece of work rather than a rewrite.

`TARGET_LANGUAGES` is deliberately conservative: only German is marked
`fully_supported`. Advertising a language whose conjugation engine and dictionary
don't exist would give learners confidently wrong grammar, which is worse than
not offering it.
"""

from __future__ import annotations

from dataclasses import dataclass

# Languages a learner can say they already speak. The tutor explains in these.
# The model handles far more than this list; it is limited to languages we can
# reasonably claim to have checked.
NATIVE_LANGUAGES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "tr": "Turkish",
    "ar": "Arabic",
    "ru": "Russian",
    "uk": "Ukrainian",
    "pl": "Polish",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "ro": "Romanian",
    "hi": "Hindi",
    "ur": "Urdu",
    "fa": "Persian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "id": "Indonesian",
}


@dataclass(frozen=True, slots=True)
class TargetLanguage:
    code: str
    name: str
    endonym: str
    # False = the LLM can still teach it, but we have no deterministic
    # conjugation engine, curated dictionary, or seeded corpus for it.
    fully_supported: bool
    speech_locale: str
    wiktionary_host: str | None = None
    tatoeba_code: str | None = None

    @property
    def has_deterministic_grammar(self) -> bool:
        """True when a rule engine — not the model — answers conjugation questions."""
        return self.fully_supported


TARGET_LANGUAGES: dict[str, TargetLanguage] = {
    "de": TargetLanguage(
        code="de",
        name="German",
        endonym="Deutsch",
        fully_supported=True,
        speech_locale="de-DE",
        wiktionary_host="de.wiktionary.org",
        tatoeba_code="deu",
    ),
    # Scaffolded, NOT enabled. Each needs a conjugation engine, a curated
    # dictionary and a seeded corpus before `fully_supported` may flip to True.
    "es": TargetLanguage("es", "Spanish", "Español", False, "es-ES", "es.wiktionary.org", "spa"),
    "fr": TargetLanguage("fr", "French", "Français", False, "fr-FR", "fr.wiktionary.org", "fra"),
    "it": TargetLanguage("it", "Italian", "Italiano", False, "it-IT", "it.wiktionary.org", "ita"),
}

DEFAULT_NATIVE = "en"
DEFAULT_TARGET = "de"


def native_name(code: str | None) -> str:
    return NATIVE_LANGUAGES.get((code or DEFAULT_NATIVE).lower(), "English")


def target(code: str | None) -> TargetLanguage:
    return TARGET_LANGUAGES.get((code or DEFAULT_TARGET).lower(), TARGET_LANGUAGES["de"])


def enabled_targets() -> list[TargetLanguage]:
    """Only languages we can actually teach correctly."""
    return [t for t in TARGET_LANGUAGES.values() if t.fully_supported]
