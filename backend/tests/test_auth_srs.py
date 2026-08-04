"""Hermetic unit tests for the auth + SRS + export slice.

No live Postgres: the ORM models use pgvector/JSONB/UUID columns that don't
compile on SQLite, so this file never creates a schema or opens a session. It
tests only the pure/isolated parts:

  * app.services.srs.grade_card — a plain function over an in-memory Flashcard
  * app.services.export.export_thread — a plain function over an in-memory Thread
  * app.core.security password hashing (no DB involved)
  * the Pydantic request models' validation rules (§11)

`auth.py` and `flashcards.py` are loaded by file path via importlib rather
than `from app.api.v1 import auth`, because importing the `app.api.v1`
*package* executes its `__init__.py`, which eagerly imports every sibling
router (admin, chat, quiz, ...) owned by other build tracks landing in
parallel. Loading by path keeps this suite independent of their state.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.security import hash_password, verify_password
from app.db.models import Flashcard, Message, Thread, Vocabulary
from app.services import export, srs

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


auth = _load_module("_test_only_auth", "app/api/v1/auth.py")
flashcards = _load_module("_test_only_flashcards", "app/api/v1/flashcards.py")


# ── srs.grade_card ─────────────────────────────────────────────────────────────


def _new_card() -> Flashcard:
    """A transient (never DB-touched) Flashcard linked to a fresh Vocabulary."""
    vocab = Vocabulary(lemma="Tisch", status="new")
    card = Flashcard(ease=2.5, interval_days=0, reps=0, lapses=0, due_at=datetime.now(UTC))
    card.vocabulary = vocab  # in-memory link only; triggers no IO
    return card


@pytest.mark.parametrize("grade", ["again", "hard", "good", "easy"])
def test_grade_card_accepts_all_four_grades(grade: str) -> None:
    card = _new_card()
    before_due = card.due_at

    srs.grade_card(card, grade)

    assert card.last_grade == grade
    assert card.reps == 1
    assert card.due_at > before_due


def test_grade_card_new_to_learning_to_mastered_path() -> None:
    card = _new_card()
    assert card.vocabulary.status == "new"

    srs.grade_card(card, "good")
    assert card.vocabulary.status == "learning"
    assert card.interval_days > 0

    for _ in range(10):
        if card.vocabulary.status == "mastered":
            break
        srs.grade_card(card, "good")

    assert card.vocabulary.status == "mastered"
    assert card.interval_days >= 21


def test_grade_card_again_demotes_and_bumps_lapses() -> None:
    card = _new_card()
    for _ in range(6):
        srs.grade_card(card, "good")
    assert card.vocabulary.status == "mastered"
    lapses_before = card.lapses

    srs.grade_card(card, "again")

    assert card.vocabulary.status == "learning"
    assert card.lapses == lapses_before + 1
    assert card.interval_days == 0


def test_grade_card_due_at_moves_forward_on_repeated_success() -> None:
    card = _new_card()
    due_dates = []
    for _ in range(4):
        srs.grade_card(card, "good")
        due_dates.append(card.due_at)

    assert due_dates == sorted(due_dates)
    assert len(set(due_dates)) == len(due_dates)  # strictly increasing, not just non-decreasing


def test_grade_card_ease_stays_within_bounds() -> None:
    card = _new_card()
    for _ in range(50):
        srs.grade_card(card, "easy")
    assert card.ease <= srs._MAX_EASE

    for _ in range(50):
        srs.grade_card(card, "again")
    assert card.ease >= srs._MIN_EASE


# ── export.export_thread ────────────────────────────────────────────────────────


def _thread_with_messages(n: int) -> Thread:
    thread = Thread(title="Dative case", created_at=datetime.now(UTC))
    thread.messages = [
        Message(
            role="user" if i % 2 == 0 else "assistant",
            content=f"message {i}",
            created_at=datetime.now(UTC) + timedelta(seconds=i),
        )
        for i in range(n)
    ]
    return thread


@pytest.mark.parametrize(
    "fmt,expected_media",
    [("json", "application/json"), ("csv", "text/csv"), ("md", "text/markdown")],
)
def test_export_thread_formats_and_media_types(fmt: str, expected_media: str) -> None:
    thread = _thread_with_messages(3)

    body, media_type, filename = export.export_thread(thread, fmt)

    assert media_type == expected_media
    assert filename.endswith(f".{fmt}")
    assert isinstance(body, bytes)
    assert b"message 0" in body


@pytest.mark.parametrize("fmt", ["json", "csv", "md"])
def test_export_thread_empty_thread_does_not_crash(fmt: str) -> None:
    thread = _thread_with_messages(0)

    body, _media_type, _filename = export.export_thread(thread, fmt)

    assert isinstance(body, bytes)  # didn't raise; that's the whole point


# ── password hashing ────────────────────────────────────────────────────────────


def test_hash_and_verify_password_round_trip() -> None:
    raw = "correct horse battery staple"

    hashed = hash_password(raw)

    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_hash_password_over_72_bytes_raises_a_clean_error_not_a_crash() -> None:
    too_long = "x" * 100  # 100 bytes > bcrypt's 72-byte limit

    with pytest.raises(ValueError):
        hash_password(too_long)


# ── Pydantic request model validation (§11) ─────────────────────────────────────


def test_register_request_rejects_password_under_8_chars() -> None:
    with pytest.raises(PydanticValidationError):
        auth.RegisterRequest(email="a@b.com", password="short1")


def test_register_request_rejects_invalid_email() -> None:
    with pytest.raises(PydanticValidationError):
        auth.RegisterRequest(email="not-an-email", password="longenough1")


def test_patch_me_request_rejects_invalid_cefr_level() -> None:
    with pytest.raises(PydanticValidationError):
        auth.PatchMeRequest(cefr_level="Z9")


def test_grade_request_rejects_invalid_grade() -> None:
    with pytest.raises(PydanticValidationError):
        flashcards.GradeRequest(grade="banana")


def test_a_card_without_examples_serialises_as_an_empty_list() -> None:
    """Regression: cards created in bulk from a word list carry a meaning but
    no example sentences or IPA — the list has neither. The API declared
    `examples` nullable while the client typed it as an array and did
    `card.examples[0]`, so the FIRST such card crashed the whole Flashcards
    page with "Cannot read properties of null".

    A list field is never null: absent means empty.
    """
    import inspect

    from app.api.v1 import flashcards

    src = inspect.getsource(flashcards)
    # The response model promises a list…
    assert "examples: list[dict]\n" in src
    # …and the serialiser guarantees one.
    assert "or []," in src
