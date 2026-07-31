"""Native/target language handling.

The tutor previously said "explain in the learner's language" without ever being
told what that language was, so everyone got English. These pin the fix.
"""

from __future__ import annotations

import pytest

from app.ai.languages import (
    NATIVE_LANGUAGES,
    TARGET_LANGUAGES,
    enabled_targets,
    native_name,
    target,
)
from app.ai.prompts import TUTOR_SYSTEM_PROMPT


def _prompt(native: str, tgt: str = "de") -> str:
    return TUTOR_SYSTEM_PROMPT.format(
        cefr_level="A2",
        native_language=native_name(native),
        target_language=target(tgt).name,
    )


@pytest.mark.parametrize(
    "code,name", [("tr", "Turkish"), ("es", "Spanish"), ("ar", "Arabic"), ("en", "English")]
)
def test_the_prompt_names_the_learners_language(code: str, name: str) -> None:
    assert name in _prompt(code)


def test_an_unknown_native_code_falls_back_to_english() -> None:
    """A bad code must not produce a prompt asking for a nonexistent language."""
    assert native_name("xx") == "English"
    assert native_name(None) == "English"


def test_the_prompt_forbids_mirroring_the_question_language() -> None:
    """The observed failure: a learner asks in German, the model replies in German.

    The instruction has to address that case by name, not merely state a default.
    """
    p = _prompt("tr")
    assert "even when the learner writes to you in" in p.lower()
    assert "do not mirror the language of the question" in p.lower()
    # Step 1 must restate it — the first sentence leaked German until it did.
    assert "including this very first sentence" in p


def test_target_language_examples_stay_in_the_target_language() -> None:
    p = _prompt("tr")
    assert "keep German words, examples, phrases and exercises in German".lower() in p.lower()


def test_only_fully_supported_languages_are_offered() -> None:
    """Advertising a language with no conjugation engine would teach wrong grammar."""
    enabled = {t.code for t in enabled_targets()}
    assert enabled == {"de"}
    assert TARGET_LANGUAGES["es"].fully_supported is False


def test_scaffolded_languages_declare_no_deterministic_grammar() -> None:
    assert target("de").has_deterministic_grammar is True
    assert TARGET_LANGUAGES["fr"].has_deterministic_grammar is False


def test_every_target_has_a_speech_locale() -> None:
    """The speaking module needs one for browser TTS."""
    for t in TARGET_LANGUAGES.values():
        assert "-" in t.speech_locale


def test_native_and_target_overlap_is_handled() -> None:
    """A German speaker learning German is degenerate but must not break."""
    p = _prompt("de", "de")
    assert "same language" in p.lower()


def test_the_native_language_list_is_not_empty_and_includes_english() -> None:
    assert "en" in NATIVE_LANGUAGES
    assert len(NATIVE_LANGUAGES) >= 10


# ── Feedback surfaces must speak the learner's language ───────────────────────
#
# Found live: writing corrections, quiz explanations and speaking corrections all
# arrived in English regardless of the learner's native language — useless to the
# A1/A2 learners they're for.


def test_writing_prompt_demands_native_language_explanations() -> None:
    from app.ai.prompts import WRITING_EVALUATE_SYSTEM_PROMPT

    p = WRITING_EVALUATE_SYSTEM_PROMPT.format(
        target_level="A2", target_language="German", native_language="Turkish"
    )
    assert "Turkish" in p
    assert "explanation" in p.lower()


def test_quiz_prompt_demands_native_language_explanations() -> None:
    from app.ai.prompts import QUIZ_GENERATE_SYSTEM_PROMPT

    p = QUIZ_GENERATE_SYSTEM_PROMPT.format(
        n=3, topic="Dativ", cefr_level="A2",
        target_language="German", native_language="Turkish",
    )
    assert "Turkish" in p


def test_speaking_score_instruction_formats_cleanly() -> None:
    """Regression: the instruction embeds a literal JSON example, and .format()
    treated its braces as fields → KeyError → the except path silently returned
    the neutral (0.7, no-corrections) score for EVERY spoken turn."""
    from app.api.v1.speaking import _SCORE_INSTRUCTION

    out = _SCORE_INSTRUCTION.format(native_language="Turkish")
    assert "Turkish" in out
    assert '{"grammar"' in out  # the JSON example survives brace-escaping
