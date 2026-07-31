"""RAG core tests — fully hermetic: no network, no real embedding calls, no DB.

Vector-store and embedding calls are never exercised here (that plumbing needs a
live Qdrant/OpenRouter to mean anything); what's covered is the pure logic this
slice owns: chunk boundaries, the SSRF guard, RRF fusion math, and parser
round-trips against local files.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.errors import ValidationError
from app.rag import chunker, parsers
from app.rag.contracts import RetrievedChunk
from app.rag.retriever import _fuse

# ── chunker ──────────────────────────────────────────────────────────────────


@pytest.fixture
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small enough to force real splitting on a short test string."""
    monkeypatch.setattr(settings, "CHUNK_TOKENS", 10)  # 40 chars
    monkeypatch.setattr(settings, "CHUNK_OVERLAP_TOKENS", 3)  # 12 chars


_HEADING_TEXT = (
    "# Einleitung\n"
    "Dies ist der erste Absatz des Einleitungskapitels und er ist ziemlich lang, "
    "damit er mehrfach aufgeteilt wird und wir Overlap sehen koennen in den "
    "erzeugten Chunks.\n\n"
    "Dies ist der zweite Absatz mit anderen Woertern, ebenfalls lang genug fuer "
    "mehrere Chunks und Ueberlappung zwischen ihnen im Text.\n\n"
    "# Grammatik\n"
    "Der Dativ wird verwendet, um das indirekte Objekt in einem Satz zu "
    "kennzeichnen und folgt bestimmten Regeln je nach Artikel und Geschlecht."
)


def test_chunk_text_splits_on_headings(small_chunks: None) -> None:
    drafts = chunker.chunk_text(_HEADING_TEXT)

    assert drafts  # produced something
    headings = {d.heading for d in drafts}
    assert headings == {"Einleitung", "Grammatik"}

    # The heading marker itself must never leak into chunk bodies — it's carried
    # as metadata (`heading`), not text to cite.
    assert not any(d.text.lstrip().startswith("#") for d in drafts)

    # Every chunk under "Grammatik" only ever contains Grammatik-section text —
    # none of it should have leaked into the "Einleitung" chunks or vice versa.
    grammatik_chunks = [d for d in drafts if d.heading == "Grammatik"]
    assert grammatik_chunks
    grammatik_text = " ".join(d.text for d in grammatik_chunks)
    assert "Dativ" in grammatik_text and "Artikel" in grammatik_text

    einleitung_text = " ".join(d.text for d in drafts if d.heading == "Einleitung")
    assert "Dativ" not in einleitung_text
    assert "Overlap" in einleitung_text


def test_chunk_text_has_no_empty_chunks_and_sequential_ordinals(small_chunks: None) -> None:
    drafts = chunker.chunk_text(_HEADING_TEXT)

    assert all(d.text.strip() for d in drafts)
    assert [d.ordinal for d in drafts] == list(range(len(drafts)))
    assert all(d.token_count > 0 for d in drafts)


def test_chunk_text_has_overlap_between_adjacent_pieces(small_chunks: None) -> None:
    drafts = chunker.chunk_text(_HEADING_TEXT)
    einleitung = [d.text for d in drafts if d.heading == "Einleitung"]
    assert len(einleitung) >= 2  # the paragraph is long enough to have split

    # Adjacent pieces from the same paragraph should share a real run of
    # characters at the boundary (RecursiveCharacterTextSplitter's overlap),
    # not just a coincidental single word.
    def shares_overlap(a: str, b: str) -> bool:
        tail = a[-12:]
        return any(tail[-n:] in b[: 12 + n] for n in range(6, len(tail) + 1))

    pairs = range(len(einleitung) - 1)
    assert any(shares_overlap(einleitung[i], einleitung[i + 1]) for i in pairs)


def test_chunk_text_never_emits_empty_pieces_for_whitespace_input(small_chunks: None) -> None:
    assert chunker.chunk_text("") == []
    assert chunker.chunk_text("   \n\n   ") == []


def test_chunk_text_tracks_page_numbers_independently() -> None:
    pages = [(1, "Seite eins Inhalt."), (2, "Seite zwei Inhalt.")]
    drafts = chunker.chunk_text("unused", pages=pages)
    assert {d.page for d in drafts} == {1, 2}
    assert all(d.text.strip() for d in drafts)


# ── SSRF guard ───────────────────────────────────────────────────────────────


def test_validate_public_url_rejects_localhost() -> None:
    with pytest.raises(ValidationError):
        parsers.validate_public_url("http://localhost/whatever")


def test_validate_public_url_rejects_loopback_literal() -> None:
    with pytest.raises(ValidationError):
        parsers.validate_public_url("http://127.0.0.1/x")


def test_validate_public_url_rejects_private_lan_literal() -> None:
    with pytest.raises(ValidationError):
        parsers.validate_public_url("http://192.168.1.1/x")


def test_validate_public_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError):
        parsers.validate_public_url("file:///etc/passwd")


def test_validate_public_url_accepts_public_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    # No live DNS in a hermetic test — stub the resolver to return a real public
    # IP for any hostname, so this test asserts our *logic*, not the network.
    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    url = "https://example.com/article"
    assert parsers.validate_public_url(url) == url


def test_validate_public_url_rejects_hostname_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DNS-rebinding shape: a public-looking hostname that resolves to a private
    # address must still be rejected — the whole point of resolving at all.
    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValidationError):
        parsers.validate_public_url("https://looks-public.example/x")


# ── RRF fusion ───────────────────────────────────────────────────────────────


def _chunk(cid: str, score: float, **kw: object) -> RetrievedChunk:
    return RetrievedChunk(
        id=cid,
        document_id=f"doc-{cid}",
        title=f"Title {cid}",
        text=f"text {cid}",
        snippet=f"text {cid}",
        score=score,
        **kw,  # type: ignore[arg-type]
    )


def test_rrf_fusion_ranks_doc_found_by_both_over_doc_found_by_one() -> None:
    # "a" is #1 in dense AND #1 in keyword; "b" is only #2 in dense; "c" is only
    # #2 in keyword. RRF's sum-of-reciprocal-ranks means "a" must win outright.
    dense = [_chunk("a", 0.9, dense_score=0.9), _chunk("b", 0.8, dense_score=0.8)]
    keyword = [_chunk("a", 5.0, keyword_score=5.0), _chunk("c", 3.0, keyword_score=3.0)]

    fused = _fuse(dense, keyword, k=10)
    ids_in_order = [c.id for c in fused]

    assert ids_in_order[0] == "a"
    by_id = {c.id: c for c in fused}
    assert by_id["a"].score > by_id["b"].score
    assert by_id["a"].score > by_id["c"].score


def test_rrf_fusion_keeps_dense_only_hits_when_no_keyword_results() -> None:
    dense = [_chunk("x", 0.5), _chunk("y", 0.4)]
    fused = _fuse(dense, [], k=10)
    assert [c.id for c in fused] == ["x", "y"]


def test_rrf_fusion_empty_inputs_yield_empty_result() -> None:
    assert _fuse([], [], k=10) == []


# ── Parsers ──────────────────────────────────────────────────────────────────


async def test_parse_markdown_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "lesson.md"
    body = "# Der Akkusativ\n\nDer Akkusativ ist der vierte Fall im Deutschen.\n"
    p.write_text(body, encoding="utf-8")

    doc = await parsers.parse("md", path=str(p))

    assert doc.title == "Der Akkusativ"
    assert "vierte Fall" in doc.text
    assert doc.pages is None


async def test_parse_txt_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    content = "Einfacher Notizentext ohne Ueberschrift."
    p.write_text(content, encoding="utf-8")

    doc = await parsers.parse("txt", path=str(p))

    assert doc.text == content
    assert doc.title  # falls back to a filename-derived title
    assert "notes" in doc.title.lower()


async def test_parse_requires_path_for_file_types() -> None:
    with pytest.raises(ValidationError):
        await parsers.parse("md", path=None)


async def test_parse_rejects_unsupported_source_type() -> None:
    with pytest.raises(ValidationError):
        await parsers.parse("carrier-pigeon", path="whatever")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2", "dQw4w9WgXcQ"),
    ],
)
def test_extract_youtube_video_id_handles_every_url_shape(url: str, expected: str) -> None:
    assert parsers.extract_youtube_video_id(url) == expected


def test_extract_youtube_video_id_rejects_garbage() -> None:
    with pytest.raises(ValidationError):
        parsers.extract_youtube_video_id("https://example.com/not-a-video")
