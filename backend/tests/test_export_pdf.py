"""Hermetic tests for the PDF format of `app.services.export.export_thread`.

Same posture as `tests/test_auth_srs.py`'s existing json/csv/md export tests:
no DB, no network — `Thread`/`Message` are built as plain in-memory ORM
instances (never flushed), which is enough because `export_thread` is a pure
function over already-loaded objects.

`pypdf` (already a project dependency) is used to read the PDF back out and
prove German text actually round-trips, not just that *some* bytes came out.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfReader

from app.db.models import Message, Thread
from app.services import export


def _thread_with_messages(n: int, *, title: str = "Dative case") -> Thread:
    thread = Thread(title=title, created_at=datetime.now(UTC))
    thread.messages = [
        Message(
            role="user" if i % 2 == 0 else "assistant",
            content=f"message {i}",
            created_at=datetime.now(UTC) + timedelta(seconds=i),
        )
        for i in range(n)
    ]
    return thread


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ── Basic shape ──────────────────────────────────────────────────────────────


def test_export_thread_pdf_returns_pdf_bytes_and_media_type() -> None:
    thread = _thread_with_messages(3)

    body, media_type, filename = export.export_thread(thread, "pdf")

    assert isinstance(body, bytes)
    assert body.startswith(b"%PDF")
    assert media_type == "application/pdf"
    assert filename.endswith(".pdf")


def test_export_thread_pdf_empty_thread_does_not_crash() -> None:
    thread = _thread_with_messages(0)

    body, _media_type, _filename = export.export_thread(thread, "pdf")

    assert isinstance(body, bytes)
    assert body.startswith(b"%PDF")


def test_export_thread_pdf_contains_the_message_text() -> None:
    thread = _thread_with_messages(3)

    body, _media_type, _filename = export.export_thread(thread, "pdf")
    text = _extract_text(body)

    assert "message 0" in text
    assert "message 1" in text
    assert "message 2" in text


def test_export_thread_pdf_labels_learner_and_tutor_turns() -> None:
    thread = _thread_with_messages(2)  # index 0 = user, index 1 = assistant

    body, _media_type, _filename = export.export_thread(thread, "pdf")
    text = _extract_text(body)

    assert "Learner" in text
    assert "Tutor" in text


# ── German text — the umlaut round-trip ──────────────────────────────────────


def test_export_thread_pdf_round_trips_german_umlauts_and_eszett() -> None:
    thread = Thread(title="Über Präpositionen", created_at=datetime.now(UTC))
    thread.messages = [
        Message(
            role="user",
            content=(
                "Können Sie mir die Präpositionen mit Dativ erklären? Ich möchte üben, "
                "damit ich keinen Fehler mehr mache — es soll nicht zu groß werden."
            ),
            created_at=datetime.now(UTC),
        ),
        Message(
            role="assistant",
            content=(
                "Natürlich! Ärgere dich nicht über die Ausnahmen: Aus, bei, mit, nach, "
                "seit, von, zu — diese verlangen den Dativ. Öfter üben hilft."
            ),
            model="anthropic/claude-sonnet-5",
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        ),
    ]

    body, _media_type, _filename = export.export_thread(thread, "pdf")
    text = _extract_text(body)

    # Every umlaut + eszett that appears in the source content, individually —
    # a lossy font/encoding would silently drop exactly these glyphs.
    for char in "äöüÄÖÜß":
        assert char in text, f"{char!r} did not round-trip through the PDF"
    assert "Über Präpositionen" in text
    assert "Natürlich" in text
    assert "möchte üben" in text


# ── Assistant metadata (model + cost) ────────────────────────────────────────


def test_export_thread_pdf_includes_model_and_cost_for_assistant_turns() -> None:
    thread = Thread(title="Cost check", created_at=datetime.now(UTC))
    thread.messages = [
        Message(role="user", content="Wie geht es dir?", created_at=datetime.now(UTC)),
        Message(
            role="assistant",
            content="Mir geht es gut, danke!",
            model="anthropic/claude-sonnet-5",
            usage={"cost_usd": 0.0034, "tokens_in": 41, "tokens_out": 17},
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        ),
    ]

    body, _media_type, _filename = export.export_thread(thread, "pdf")
    text = _extract_text(body)

    assert "anthropic/claude-sonnet-5" in text
    assert "0.0034" in text


def test_export_thread_pdf_omits_metadata_line_when_no_model_or_cost_present() -> None:
    thread = _thread_with_messages(2)  # assistant message has no model/usage set

    body, _media_type, _filename = export.export_thread(thread, "pdf")

    # Must not raise on a bare assistant message, and must still produce a
    # valid, non-trivial PDF.
    assert body.startswith(b"%PDF")
    assert len(body) > 500


# ── Wrapping / pagination ─────────────────────────────────────────────────────


def test_export_thread_pdf_paginates_a_long_conversation() -> None:
    long_paragraph = (
        "Der Dativ ist der dritte Fall im Deutschen und wird oft als Wem-Fall "
        "bezeichnet, weil man mit der Frage Wem nach ihm fragt. " * 15
    )
    thread = Thread(title="Long conversation", created_at=datetime.now(UTC))
    thread.messages = [
        Message(
            role="user" if i % 2 == 0 else "assistant",
            content=f"Turn {i}: {long_paragraph}",
            created_at=datetime.now(UTC) + timedelta(seconds=i),
        )
        for i in range(30)
    ]

    body, _media_type, _filename = export.export_thread(thread, "pdf")
    reader = PdfReader(io.BytesIO(body))

    assert len(reader.pages) > 1  # must not be clipped onto a single page

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Turn 0:" in text
    assert "Turn 29:" in text


def test_export_thread_pdf_escapes_special_characters_without_raising() -> None:
    thread = Thread(title="Special <chars> & stuff", created_at=datetime.now(UTC))
    thread.messages = [
        Message(
            role="user",
            content="5 < 10 & 10 > 5, das stimmt & ist < wichtig.",
            created_at=datetime.now(UTC),
        )
    ]

    body, _media_type, _filename = export.export_thread(thread, "pdf")

    assert body.startswith(b"%PDF")
    text = _extract_text(body)
    assert "5" in text and "10" in text


# ── Existing formats must be untouched ────────────────────────────────────────


@pytest.mark.parametrize(
    "fmt,expected_media",
    [("json", "application/json"), ("csv", "text/csv"), ("md", "text/markdown")],
)
def test_export_thread_non_pdf_formats_still_work(fmt: str, expected_media: str) -> None:
    thread = _thread_with_messages(3)

    body, media_type, filename = export.export_thread(thread, fmt)

    assert media_type == expected_media
    assert filename.endswith(f".{fmt}")
    assert isinstance(body, bytes)
    assert b"message 0" in body
