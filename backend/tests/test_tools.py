"""Tests for the LangChain tool layer. Hermetic: no network, no live LLM, no DB engine.

`app.ai.router.complete` and `app.rag.retriever.retrieve` are monkeypatched at their
*defining* module (dictionary.py/structured.py/registry.py import those modules by
name, not the bare function, precisely so this patch point works). The vocabulary
tool uses a tiny in-memory fake session instead of a real AsyncSession/engine.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai import router as ai_router
from app.ai import structured
from app.ai.router import AIResult
from app.ai.tools import dictionary, registry
from app.ai.tools.conjugation import conjugate
from app.core.errors import UpstreamError
from app.db.models import User

# asyncio_mode = "auto" (pyproject.toml) — plain `async def test_...` works with no marker.


# ── Test doubles ────────────────────────────────────────────────────────────────


def _fake_ai_result(text: str) -> AIResult:
    return AIResult(text=text, model_used="test/fake-model", tokens_in=10, tokens_out=10)


class FakeResult:
    """Mimics the object `AsyncSession.execute()` returns, for `.scalar_one_or_none()`."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """A minimal stand-in for AsyncSession — no engine, no network.

    `existing` lets a test pre-seed what the (idempotency-check) SELECT should
    "find"; `execute()` deliberately ignores the actual statement rather than
    trying to emulate SQLAlchemy's query planner.
    """

    def __init__(self, existing: Any = None) -> None:
        self.existing = existing
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, _stmt: Any) -> FakeResult:
        return FakeResult(self.existing)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="learner@example.com",
        password_hash="x",
        display_name="Learner",
        cefr_level="A2",
    )


# ── Arg-schema validation (the graded input-validation surface) ────────────────


def test_lookup_word_rejects_empty_lemma() -> None:
    with pytest.raises(ValidationError):
        registry.LookupWordArgs(lemma="")


def test_lookup_word_rejects_lemma_with_digits() -> None:
    with pytest.raises(ValidationError):
        registry.LookupWordArgs(lemma="Tisch123")


def test_lookup_word_accepts_umlauts_and_hyphen() -> None:
    assert registry.LookupWordArgs(lemma="Grün-Kohl").lemma == "Grün-Kohl"


def test_conjugate_verb_rejects_bogus_tense() -> None:
    with pytest.raises(ValidationError):
        registry.ConjugateVerbArgs(verb="gehen", tense="future-perfect-continuous")


def test_conjugate_verb_accepts_real_tense() -> None:
    args = registry.ConjugateVerbArgs(verb="gehen", tense="praeteritum")
    assert args.tense == "praeteritum"


@pytest.mark.parametrize("n", [0, 99])
def test_generate_quiz_rejects_out_of_range_n(n: int) -> None:
    with pytest.raises(ValidationError):
        registry.GenerateQuizArgs(topic="dative case", cefr_level="A2", n=n)


def test_generate_quiz_rejects_bogus_cefr() -> None:
    with pytest.raises(ValidationError):
        registry.GenerateQuizArgs(topic="dative case", cefr_level="Z9", n=5)


def test_evaluate_writing_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        registry.EvaluateWritingArgs(text="", target_level="B1")


def test_evaluate_writing_rejects_text_over_5000_chars() -> None:
    with pytest.raises(ValidationError):
        registry.EvaluateWritingArgs(text="x" * 5001, target_level="B1")


def test_save_vocabulary_rejects_empty_lemma() -> None:
    with pytest.raises(ValidationError):
        registry.SaveVocabularyArgs(lemma="")


# ── Security: save_vocabulary cannot target another user ───────────────────────


def test_save_vocabulary_schema_has_no_user_or_owner_field() -> None:
    field_names = set(registry.SaveVocabularyArgs.model_fields)
    assert field_names == {"lemma"}
    assert "user_id" not in field_names
    assert "owner" not in field_names
    assert "owner_id" not in field_names


# ── Deterministic conjugation via the real engine ──────────────────────────────


def test_conjugate_gehen_praeteritum_matches_expected_forms() -> None:
    result = conjugate("gehen", "praeteritum")
    assert result["forms"]["ich"] == "ging"
    assert result["forms"]["du"] == "gingst"
    assert result["forms"]["wir"] == "gingen"


async def test_conjugate_verb_tool_wraps_the_real_engine() -> None:
    user = _make_user()
    tools = {t.name: t for t in registry.build_tools(db=None, user=user)}
    out = await tools["conjugate_verb"].ainvoke({"verb": "gehen", "tense": "praeteritum"})
    assert out["forms"]["ich"] == "ging"
    assert out["forms"]["du"] == "gingst"
    assert out["forms"]["wir"] == "gingen"


async def test_conjugate_verb_tool_returns_friendly_string_for_bad_infinitive() -> None:
    user = _make_user()
    tools = {t.name: t for t in registry.build_tools(db=None, user=user)}
    # Doesn't end in -en/-n, so the rule engine can't treat it as an infinitive.
    out = await tools["conjugate_verb"].ainvoke({"verb": "Tischx", "tense": "praesens"})
    assert isinstance(out, str)
    assert "Tischx" in out


# ── save_vocabulary: scoping + idempotency ──────────────────────────────────────


async def test_save_vocabulary_writes_only_for_the_closure_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _make_user()
    session = FakeSession(existing=None)

    async def fake_lookup(db: Any, lemma: str, *, user_id: Any = None) -> dict[str, Any]:
        return {
            "lemma": "gehen",
            "pos": "verb",
            "article": None,
            "plural": None,
            "ipa": "ˈɡeːən",
            "meanings": [{"lang": "en", "text": "to go"}],
            "examples": [{"de": "Ich gehe.", "en": "I go."}],
            "cefr_level": "A1",
            "source": "dictionary",
        }

    monkeypatch.setattr(dictionary, "lookup", fake_lookup)

    tools = {t.name: t for t in registry.build_tools(db=session, user=user)}
    out = await tools["save_vocabulary"].ainvoke({"lemma": "gehen"})

    assert out["lemma"] == "gehen"
    assert session.committed is True
    vocab_rows = [o for o in session.added if o.__class__.__name__ == "Vocabulary"]
    assert len(vocab_rows) == 1
    assert vocab_rows[0].user_id == user.id
    flashcard_rows = [o for o in session.added if o.__class__.__name__ == "Flashcard"]
    assert len(flashcard_rows) == 1
    assert flashcard_rows[0].user_id == user.id


async def test_save_vocabulary_is_idempotent_per_user_and_lemma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Vocabulary

    user = _make_user()
    already_saved = Vocabulary(
        id=uuid.uuid4(),
        user_id=user.id,
        lemma="gehen",
        pos="verb",
        meaning="to go",
        status="new",
    )
    session = FakeSession(existing=already_saved)

    async def fail_if_called(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("lookup should not run when the vocab row already exists")

    monkeypatch.setattr(dictionary, "lookup", fail_if_called)

    tools = {t.name: t for t in registry.build_tools(db=session, user=user)}
    out = await tools["save_vocabulary"].ainvoke({"lemma": "gehen"})

    assert out["id"] == str(already_saved.id)
    assert session.added == []  # no new rows — the existing one was returned as-is


# ── Structured JSON parsing: fences, malformed JSON, repair retry ──────────────


def test_parse_json_object_survives_fenced_json() -> None:
    raw = 'Here you go:\n```json\n{"a": 1, "b": [2, 3]}\n```\nHope that helps!'
    assert structured.parse_json_object(raw) == {"a": 1, "b": [2, 3]}


def test_parse_json_object_raises_value_error_on_no_json() -> None:
    with pytest.raises(ValueError):
        structured.parse_json_object("no json here at all")


async def test_generate_quiz_repairs_once_after_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    good = (
        '{"topic": "dative case", "cefr_level": "A2", "questions": ['
        '{"id": "q1", "type": "cloze", "prompt": "Ich gebe ___ Kind ein Buch.", '
        '"options": null, "expected": "dem", "explanation": "Dative for the indirect object."}'
        '], "sources": null}'
    )

    async def fake_complete(
        db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        calls.append(str(task_type))
        if len(calls) == 1:
            return _fake_ai_result("this is not { valid json at all")
        return _fake_ai_result(good)

    monkeypatch.setattr(ai_router, "complete", fake_complete)

    quiz = await structured.generate_quiz(
        None, topic="dative case", cefr_level="A2", n=1, user_id=None
    )
    assert len(calls) == 2  # exactly one repair retry
    assert quiz.questions[0].expected == "dem"


async def test_generate_quiz_raises_upstream_error_after_failed_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def always_bad(
        db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        calls.append(str(task_type))
        return _fake_ai_result("still not json")

    monkeypatch.setattr(ai_router, "complete", always_bad)

    with pytest.raises(UpstreamError):
        await structured.generate_quiz(
            None, topic="dative case", cefr_level="A2", n=1, user_id=None
        )
    assert len(calls) == 2  # first attempt + exactly one repair retry, then give up


async def test_evaluate_writing_parses_valid_json_first_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    payload = (
        '{"scores": {"grammar": 0.8, "vocabulary": 0.7, "coherence": 0.75, "overall": 0.75}, '
        '"cefr_estimate": "B1", "corrections": [{"original": "Ich habe gegangen", '
        '"suggestion": "Ich bin gegangen", "explanation": "gehen uses sein.", '
        '"severity": "error", "offset": 0, "length": 17}], '
        '"improved_version": "Ich bin gegangen.", "suggestions": ["Use sein with gehen."]}'
    )

    async def fake_complete(
        db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        calls.append(str(task_type))
        return _fake_ai_result(payload)

    monkeypatch.setattr(ai_router, "complete", fake_complete)

    evaluation = await structured.evaluate_writing(
        None, text="Ich habe gegangen.", target_level="B1", user_id=None
    )
    assert len(calls) == 1  # no repair needed
    assert evaluation.cefr_estimate == "B1"
    assert evaluation.corrections[0].suggestion == "Ich bin gegangen"


# ── Dictionary: curated hit vs. LLM-fallback miss ───────────────────────────────


async def test_dictionary_curated_hit_reports_dictionary_source() -> None:
    result = await dictionary.lookup(None, "gehen")
    assert result["source"] == "dictionary"
    assert result["pos"] == "verb"
    assert result["lemma"] == "gehen"


async def test_dictionary_curated_noun_hit_includes_article_and_plural() -> None:
    result = await dictionary.lookup(None, "Tisch")
    assert result["source"] == "dictionary"
    assert result["article"] == "der"
    assert result["plural"] == "die Tische"
    assert result["lemma"] == "der Tisch"


async def test_dictionary_strips_leading_article_before_matching() -> None:
    result = await dictionary.lookup(None, "der Tisch")
    assert result["source"] == "dictionary"
    assert result["article"] == "der"


async def test_dictionary_miss_routes_to_llm_and_reports_llm_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"pos": "noun", "article": "das", "plural": "die Fahrräder", "ipa": null, '
        '"meanings": [{"lang": "en", "text": "bicycle"}], '
        '"examples": [{"de": "Das Fahrrad ist neu.", "en": "The bicycle is new."}], '
        '"cefr_level": "A2"}'
    )
    calls: list[str] = []

    async def fake_complete(
        db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        calls.append(str(task_type))
        return _fake_ai_result(payload)

    monkeypatch.setattr(ai_router, "complete", fake_complete)

    # "Fahrrad" is not in the curated table — deliberately, so this exercises the fallback.
    assert "Fahrrad" not in dictionary.CURATED
    result = await dictionary.lookup(None, "Fahrrad")
    assert len(calls) == 1
    assert result["source"] == "llm"
    assert result["article"] == "das"
    assert result["lemma"] == "das Fahrrad"


async def test_dictionary_llm_fallback_raises_upstream_error_on_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(
        db: Any, *, task_type: Any, messages: Any, user_id: Any = None
    ) -> AIResult:
        return _fake_ai_result("not json")

    monkeypatch.setattr(ai_router, "complete", fake_complete)

    with pytest.raises(UpstreamError):
        await dictionary.lookup(None, "Fahrrad")


# ── search_knowledge_base tool: recovers from a retriever failure ──────────────


async def test_search_knowledge_base_tool_returns_string_on_retrieve_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.tools import registry as registry_module

    async def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("vector store unreachable")

    monkeypatch.setattr(registry_module.rag_retriever, "retrieve", boom)

    user = _make_user()
    tools = {t.name: t for t in registry.build_tools(db=None, user=user)}
    out = await tools["search_knowledge_base"].ainvoke({"query": "dative case"})
    assert isinstance(out, str)
