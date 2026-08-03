"""Admin-editable prompts — the validation contract.

An override goes straight into `str.format(**fixed_kwargs)` on the hot path,
so what's worth pinning is exactly what can break there: an unknown
placeholder (KeyError → the tutor is down), a missing one (silent teaching
degradation), and a stray single brace (ValueError). Plus the self-check that
every registry DEFAULT satisfies its own spec — a spec nobody can save under
is a config trap.
"""

from __future__ import annotations

import pytest

from app.ai import prompt_registry as reg
from app.core.errors import ValidationError

TUTOR = reg.REGISTRY["tutor_system"]


def _valid_tutor_text() -> str:
    return (
        "You teach {target_language} to a {cefr_level} learner. "
        "Always explain in {native_language} and keep examples in {target_language}."
    )


# ── Every default is saveable under its own rules ─────────────────────────────


@pytest.mark.parametrize("key", sorted(reg.REGISTRY))
def test_every_default_passes_its_own_validation(key: str) -> None:
    spec = reg.REGISTRY[key]
    reg.validate_override(spec, spec.default)  # must not raise


@pytest.mark.parametrize("key", sorted(reg.REGISTRY))
def test_every_default_formats_with_its_declared_placeholders(key: str) -> None:
    spec = reg.REGISTRY[key]
    spec.default.format(**{k: "x" for k in spec.placeholders})  # must not raise


# ── Override validation ───────────────────────────────────────────────────────


def test_a_wellformed_override_is_accepted() -> None:
    reg.validate_override(TUTOR, _valid_tutor_text())


def test_unknown_placeholder_is_rejected_by_name() -> None:
    """{learner_name} isn't passed by the call site — saving it would KeyError
    on the next tutor turn. The error must name the offender."""
    bad = _valid_tutor_text() + " Greet {learner_name} warmly."
    with pytest.raises(ValidationError, match="learner_name"):
        reg.validate_override(TUTOR, bad)


def test_missing_required_placeholder_is_rejected() -> None:
    """Dropping {cefr_level} means the tutor no longer knows the level."""
    bad = "Explain everything in {native_language} with {target_language} examples only."
    with pytest.raises(ValidationError, match="cefr_level"):
        reg.validate_override(TUTOR, bad)


def test_stray_single_brace_is_rejected() -> None:
    bad = _valid_tutor_text() + ' Return JSON like {"score": 1}.'
    with pytest.raises(ValidationError):
        reg.validate_override(TUTOR, bad)


def test_doubled_braces_are_fine_json_examples_stay_writable() -> None:
    ok = _valid_tutor_text() + ' Return JSON like {{"score": 1}}.'
    reg.validate_override(TUTOR, ok)


def test_too_short_is_rejected() -> None:
    scoring = reg.REGISTRY["speaking_grammar_scoring"]
    with pytest.raises(ValidationError, match="short"):
        reg.validate_override(scoring, "{native_language}")


def test_length_cap() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        reg.validate_override(TUTOR, _valid_tutor_text() + "x" * 9000)


# ── Placeholder extraction ────────────────────────────────────────────────────


def test_extraction_ignores_escaped_json_braces() -> None:
    assert reg.extract_placeholders('{{"a": 1}} uses {topic} and {cefr}') == {
        "topic",
        "cefr",
    }
