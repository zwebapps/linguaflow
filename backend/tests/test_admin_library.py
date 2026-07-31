"""Tests for the admin knowledge-base API, the ingestion pipeline, and the
library API. Fully hermetic: no network, no live embeddings, no Postgres.

`admin.py` and `library.py` are loaded by file path via `importlib` rather than
`from app.api.v1 import admin` — same reasoning as `test_auth_srs.py`: importing
the `app.api.v1` *package* runs its `__init__.py`, which eagerly imports every
sibling router. Loading by path keeps this suite independent of that.

`app.rag.ingest` and `app.workers.ingest` import cleanly on their own (they sit
outside `app.api.v1`), so those are imported normally.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.db.models import AIUsage, Document, User
from app.rag import ingest as ingest_module
from app.rag.parsers import ParsedDoc

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


admin = _load_module("_test_only_admin", "app/api/v1/admin.py")
library = _load_module("_test_only_library", "app/api/v1/library.py")


# ── Shared doubles ───────────────────────────────────────────────────────────────


def _make_admin_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="x",
        display_name="Admin",
        role="admin",
        cefr_level="C1",
    )


class FakeSession:
    """Minimal AsyncSession stand-in — no engine, no network.

    Good enough for routes that fail fast (validation) before touching the DB;
    routes that need real query results build a purpose-specific fake instead
    (see `_FakeIngestSession` below).
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, _stmt: Any) -> Any:
        raise AssertionError("this test should fail before any query runs")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def get(self, _model: Any, _pk: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class _FakeUploadFile:
    """Just enough of Starlette's `UploadFile` surface for `_save_upload`."""

    def __init__(self, filename: str, data: bytes, chunk_size: int = 1024 * 1024) -> None:
        self.filename = filename
        self._data = data
        self._chunk_size = chunk_size
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        size = self._chunk_size if n in (-1, None) else n
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    async def close(self) -> None:
        pass


# ── Upload validation ────────────────────────────────────────────────────────────


def test_upload_rejects_exe_extension() -> None:
    with pytest.raises(ValidationError):
        admin._validate_extension("virus.exe")


def test_upload_accepts_every_contract_extension() -> None:
    for ext, expected_type in {
        ".pdf": "pdf",
        ".epub": "epub",
        ".docx": "docx",
        ".md": "md",
        ".html": "html",
        ".txt": "txt",
    }.items():
        assert admin._validate_extension(f"lesson{ext}") == expected_type


async def test_upload_rejects_oversized_file_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(admin.settings, "MAX_UPLOAD_MB", 0)  # zero-byte cap

    fake_file = _FakeUploadFile("notes.txt", b"more than zero bytes of content")
    with pytest.raises(ValidationError):
        await admin._save_upload(fake_file)

    # The size cap must be enforced while streaming, and a rejected upload must
    # never leave a partial file behind on disk.
    assert list(tmp_path.iterdir()) == []  # noqa: ASYNC240 - test assertion, not app code


async def test_upload_streams_within_limit_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(admin.settings, "MAX_UPLOAD_MB", 25)

    body = b"Der Dativ ist der dritte Fall."
    fake_file = _FakeUploadFile("lesson.md", body)
    storage_path, source_type = await admin._save_upload(fake_file)

    assert source_type == "md"
    assert Path(storage_path).read_bytes() == body  # noqa: ASYNC240 - test assertion


# ── SSRF guard on /documents/link ────────────────────────────────────────────────


async def test_link_document_rejects_localhost_url() -> None:
    payload = admin.LinkDocumentRequest(url="http://localhost/feed.xml", source_type="web")
    with pytest.raises(ValidationError):
        await admin.link_document(payload, db=FakeSession(), admin=_make_admin_user())


async def test_create_feed_rejects_private_ip_url() -> None:
    payload = admin.FeedCreateRequest(url="http://192.168.1.5/feed.xml")
    with pytest.raises(ValidationError):
        await admin.create_feed(payload, db=FakeSession(), admin=_make_admin_user())


# ── PUT /ai-routes/{task_type} ───────────────────────────────────────────────────


async def test_update_ai_route_rejects_unknown_task_type() -> None:
    payload = admin.UpdateAIRouteRequest(primary_model="openai/gpt-4o")
    with pytest.raises(ValidationError):
        await admin.update_ai_route(
            "not_a_real_task", payload, db=FakeSession(), admin=_make_admin_user()
        )


def test_update_ai_route_request_requires_a_model_id() -> None:
    with pytest.raises(PydanticValidationError):
        admin.UpdateAIRouteRequest(primary_model="")


async def test_validate_model_id_allows_anything_when_catalog_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.errors import UpstreamError

    async def broken_catalog(*_a: Any, **_kw: Any) -> Any:
        raise UpstreamError("OpenRouter is down")

    monkeypatch.setattr(admin, "fetch_catalog", broken_catalog)
    # Must not raise: a flaky third party can never block an admin's edit.
    await admin._validate_model_id("some/totally-made-up-model")


async def test_validate_model_id_rejects_model_not_in_a_reachable_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_catalog(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return [{"id": "openai/gpt-4o"}]

    monkeypatch.setattr(admin, "fetch_catalog", fake_catalog)
    with pytest.raises(ValidationError):
        await admin._validate_model_id("nonexistent/model")


# ── GET /usage maths ─────────────────────────────────────────────────────────────


def _usage_row(
    *,
    tokens_in: int,
    tokens_out: int,
    cost_micro: int,
    from_cache: bool,
    task: str,
    model: str,
    day: str,
) -> AIUsage:
    return AIUsage(
        id=uuid.uuid4(),
        user_id=None,
        task_type=task,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_micro_usd=cost_micro,
        latency_ms=10,
        from_cache=from_cache,
        fallback_used=False,
        created_at=datetime.fromisoformat(f"{day}T00:00:00+00:00"),
    )


def test_aggregate_usage_converts_micro_usd_to_usd_and_totals_calls() -> None:
    rows = [
        _usage_row(
            tokens_in=100, tokens_out=50, cost_micro=1_500_000, from_cache=False,
            task="chat", model="m1", day="2026-07-01",
        ),
        _usage_row(
            tokens_in=200, tokens_out=80, cost_micro=500_000, from_cache=True,
            task="chat", model="m2", day="2026-07-01",
        ),
    ]

    result = admin.aggregate_usage(rows, "day")

    assert result.total.tokens_in == 300
    assert result.total.tokens_out == 130
    assert result.total.calls == 2
    assert result.total.cost_usd == pytest.approx(2.0)
    assert len(result.series) == 1
    assert result.series[0].key == "2026-07-01"
    assert result.series[0].cost_usd == pytest.approx(2.0)


def test_aggregate_usage_cache_hit_rate_and_grouping_by_model() -> None:
    rows = [
        _usage_row(
            tokens_in=10, tokens_out=5, cost_micro=100, from_cache=True,
            task="chat", model="m1", day="2026-07-01",
        ),
        _usage_row(
            tokens_in=10, tokens_out=5, cost_micro=100, from_cache=False,
            task="chat", model="m2", day="2026-07-02",
        ),
        _usage_row(
            tokens_in=10, tokens_out=5, cost_micro=100, from_cache=False,
            task="chat", model="m1", day="2026-07-03",
        ),
    ]

    result = admin.aggregate_usage(rows, "model")

    assert result.total.cache_hit_rate == pytest.approx(1 / 3, abs=1e-4)
    keys = {point.key for point in result.series}
    assert keys == {"m1", "m2"}
    m1 = next(p for p in result.series if p.key == "m1")
    assert m1.calls == 2


def test_aggregate_usage_zero_calls_does_not_divide_by_zero() -> None:
    result = admin.aggregate_usage([], "day")
    assert result.total.calls == 0
    assert result.total.cache_hit_rate == 0.0
    assert result.series == []


# ── Ingestion pipeline ────────────────────────────────────────────────────────────


class _FakeVectorStore:
    def __init__(self) -> None:
        self.upsert_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.deleted: list[tuple[str, str]] = []

    async def delete_by_document(self, collection: str, document_id: str) -> None:
        self.deleted.append((collection, document_id))

    async def upsert(self, collection: str, chunks: list[dict[str, Any]]) -> None:
        self.upsert_calls.append((collection, chunks))

    async def health(self) -> bool:
        return True


class _FakeEmbedder:
    dim = 4

    def __init__(self) -> None:
        self.embed_calls: list[list[str]] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class _FakeExecResult:
    """Returned by `_FakeIngestSession.execute()` — never meaningfully queried
    in these tests because the duplicate-lookup path is monkeypatched directly
    (see `_find_duplicate` below), the same style test_tools.py uses for
    `dictionary.lookup`."""

    def scalars(self) -> _FakeExecResult:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def scalar_one_or_none(self) -> None:
        return None


class _FakeIngestSession:
    def __init__(self, document: Document) -> None:
        self._by_id: dict[uuid.UUID, Document] = {document.id: document}
        self.added: list[Any] = []
        self.rolled_back = False

    async def get(self, model: Any, pk: Any) -> Any:
        if model is Document:
            return self._by_id.get(pk)
        return None

    async def execute(self, _stmt: Any) -> _FakeExecResult:
        return _FakeExecResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        self.rolled_back = True


def _pending_document(**overrides: Any) -> Document:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        title="Test doc",
        source_type="md",
        storage_path="/tmp/whatever.md",
        collection="grammar_documents",
        status="pending",
        chunk_count=0,
    )
    defaults.update(overrides)
    return Document(**defaults)


async def test_ingest_document_marks_failed_on_parse_error_and_never_stuck_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pending_document()
    session = _FakeIngestSession(document)

    async def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("parse exploded")

    monkeypatch.setattr(ingest_module, "parse", boom)
    monkeypatch.setattr(ingest_module, "get_vector_store", lambda: _FakeVectorStore())

    await ingest_module.ingest_document(session, document.id)

    assert document.status == "failed"
    assert document.status != "processing"
    assert document.error is not None
    assert "parse exploded" in document.error


async def test_ingest_document_missing_row_is_a_no_op() -> None:
    session = _FakeIngestSession(_pending_document())
    # A random id that isn't in the fake session's store at all.
    await ingest_module.ingest_document(session, uuid.uuid4())  # must not raise


async def test_ingest_document_duplicate_content_hash_skips_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pending_document(title="Duplicate candidate")
    session = _FakeIngestSession(document)

    async def fake_parse(
        source_type: str, *, path: str | None = None, url: str | None = None
    ) -> ParsedDoc:
        return ParsedDoc(
            title="Duplicate candidate", text="Hallo Welt, das ist ein Test.", pages=None
        )

    monkeypatch.setattr(ingest_module, "parse", fake_parse)
    monkeypatch.setattr(ingest_module, "get_vector_store", lambda: _FakeVectorStore())

    fake_embedder = _FakeEmbedder()
    monkeypatch.setattr(ingest_module, "get_embedder", lambda: fake_embedder)

    original = _pending_document(title="Original", status="ready")

    async def fake_find_duplicate(
        _db: Any, _content_hash: str, *, exclude_id: uuid.UUID
    ) -> Document:
        return original

    monkeypatch.setattr(ingest_module, "_find_duplicate", fake_find_duplicate)

    await ingest_module.ingest_document(session, document.id)

    assert document.status == "failed"
    assert "duplicate" in (document.error or "").lower()
    assert str(original.id) in (document.error or "")
    assert fake_embedder.embed_calls == []  # never reached the embedding step


async def test_ingest_document_happy_path_embeds_and_marks_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pending_document(title="Der Dativ", cefr_level="A2", skill="grammar")
    session = _FakeIngestSession(document)

    async def fake_parse(
        source_type: str, *, path: str | None = None, url: str | None = None
    ) -> ParsedDoc:
        return ParsedDoc(
            title="Der Dativ",
            text="# Der Dativ\n\nDer Dativ ist der dritte Fall im Deutschen.",
            pages=None,
        )

    monkeypatch.setattr(ingest_module, "parse", fake_parse)

    async def no_duplicate(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(ingest_module, "_find_duplicate", no_duplicate)

    fake_store = _FakeVectorStore()
    fake_embedder = _FakeEmbedder()
    monkeypatch.setattr(ingest_module, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(ingest_module, "get_embedder", lambda: fake_embedder)

    await ingest_module.ingest_document(session, document.id)

    assert document.status == "ready"
    assert document.error is None
    assert document.chunk_count > 0
    assert document.content_md
    assert fake_embedder.embed_calls  # embedding did run
    assert fake_store.upsert_calls  # vectors were written


# ── Library API ──────────────────────────────────────────────────────────────────


def test_library_list_view_matches_the_contract_shape() -> None:
    document = _pending_document(
        title="Ein Tag im Park",
        status="ready",
        chunk_count=6,
        reading_minutes=5,
        cefr_level="A1",
        skill="reading",
        created_at=datetime.now(UTC),
    )

    item = library._list_view(document)

    assert item.id == str(document.id)
    assert item.chunk_count == 6
    assert item.reading_minutes == 5
    assert set(item.model_dump()) == {
        "id", "title", "source_type", "cefr_level", "skill",
        "chunk_count", "reading_minutes", "created_at",
    }


def test_library_detail_view_includes_content_md() -> None:
    document = _pending_document(
        title="Der Dativ",
        status="ready",
        content_md="# Der Dativ\n\n...",
        created_at=datetime.now(UTC),
    )

    detail = library._detail_view(document)

    assert detail.content_md == "# Der Dativ\n\n..."
    assert "content_md" in detail.model_dump()
