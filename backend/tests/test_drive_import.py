"""Google Drive imports.

The field failure these pin: an admin pasted a Drive FOLDER share link as a web
import, the fetcher got Google's JavaScript shell (a folder page has no document
text in its HTML), and the learner ended up with a "document" that was nothing
but the link. Drive links must therefore never reach the generic web scraper —
folders fail loudly with instructions, file links are rewritten to the
direct-download endpoint and the payload is sniffed by magic bytes.

Everything here is hermetic: the fetch layer is monkeypatched, no request leaves
the process.
"""

from __future__ import annotations

import io

import pypdf
import pytest

from app.core.errors import UpstreamError, ValidationError
from app.rag import parsers

FOLDER_URL = (
    "https://drive.google.com/drive/folders/1w69gWrjaWgp115jSm0SskZCZLTUDvxqS"
    "?fbclid=abc&sort=13&direction=a"
)


def _fake_fetch(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[str]:
    """Route parsers._fetch_bytes/_fetch_text to a canned payload; record URLs."""
    calls: list[str] = []

    async def fetch(url: str) -> bytes:
        calls.append(url)
        return payload

    async def fetch_text(url: str) -> str:
        calls.append(url)
        return payload.decode("utf-8", errors="replace")

    monkeypatch.setattr(parsers, "_fetch_bytes", fetch)
    monkeypatch.setattr(parsers, "_fetch_text", fetch_text)
    return calls


def _tiny_pdf(text: str = "Der Dativ ist der dritte Fall.") -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Der Dativ"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── URL recognition ───────────────────────────────────────────────────────────


def test_drive_hosts_are_recognised() -> None:
    assert parsers.is_google_drive_url(FOLDER_URL)
    assert parsers.is_google_drive_url("https://docs.google.com/document/d/abc123/edit")
    assert not parsers.is_google_drive_url("https://example.com/drive/folders/x")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://drive.google.com/file/d/FILE42/view?usp=sharing", "FILE42"),
        ("https://drive.google.com/open?id=FILE42", "FILE42"),
        ("https://drive.google.com/uc?export=download&id=FILE42", "FILE42"),
        ("https://drive.google.com/drive/my-drive", None),
    ],
)
def test_file_id_extraction(url: str, expected: str | None) -> None:
    assert parsers._drive_file_id(url) == expected


# ── Folder links fail with instructions, not with an empty document ───────────


@pytest.mark.asyncio
async def test_folder_link_is_rejected_with_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original bug: a folder link must never produce a link-only document."""
    calls = _fake_fetch(monkeypatch, b"<html>drive shell</html>")
    with pytest.raises(ValidationError) as exc:
        await parsers.parse("web", url=FOLDER_URL)
    message = str(exc.value)
    assert "FOLDER" in message and "share link" in message
    assert calls == []  # rejected before any network fetch


# ── File links fetch the real content ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_link_is_rewritten_to_direct_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_fetch(monkeypatch, b"Der Dativ\n\nDem Mann, der Frau, dem Kind.")
    doc = await parsers.parse(
        "web", url="https://drive.google.com/file/d/FILE42/view?usp=sharing"
    )
    assert calls == ["https://drive.google.com/uc?export=download&id=FILE42"]
    assert doc.title == "Der Dativ"
    assert "dem Kind" in doc.text


@pytest.mark.asyncio
async def test_pdf_payload_goes_through_the_pdf_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_fetch(monkeypatch, _tiny_pdf())
    doc = await parsers.parse("web", url="https://drive.google.com/file/d/F1/view")
    assert doc.title == "Der Dativ"  # from PDF metadata, not the temp filename


@pytest.mark.asyncio
async def test_html_instead_of_file_means_not_shared_or_too_big(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sign-in page / virus-scan interstitial must not be ingested as content."""
    _fake_fetch(
        monkeypatch,
        b"<!DOCTYPE html><html><body>Google Drive - Virus scan warning</body></html>",
    )
    with pytest.raises(UpstreamError) as exc:
        await parsers.parse("web", url="https://drive.google.com/file/d/F1/view")
    assert "Anyone with the link" in str(exc.value)


@pytest.mark.asyncio
async def test_google_doc_uses_the_txt_export(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_fetch(monkeypatch, "Wochenplan\nMontag: Dativ üben.".encode())
    doc = await parsers.parse(
        "web", url="https://docs.google.com/document/d/DOC7/edit?usp=sharing"
    )
    assert calls == ["https://docs.google.com/document/d/DOC7/export?format=txt"]
    assert doc.title == "Wochenplan"
    assert "Montag" in doc.text


@pytest.mark.asyncio
async def test_non_drive_urls_still_use_the_generic_scraper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_fetch(
        monkeypatch,
        b"<html><head><title>Lektion</title></head><body><article><p>"
        b"Der Akkusativ folgt auf durch, f\xc3\xbcr, gegen, ohne, um.</p>"
        b"</article></body></html>",
    )
    doc = await parsers.parse("web", url="https://example.com/lektion")
    assert "Akkusativ" in doc.text
