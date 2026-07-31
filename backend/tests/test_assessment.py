"""Tests for the assessment + analysis slice: quiz grading, writing evaluation,
and the pure scoring helpers behind `GET /analysis`.

Hermetic — no network, no live LLM, no Postgres. `app.ai.structured` and
`app.rag.retriever` are monkeypatched at their *defining* modules (quiz.py
imports them by module, not by bare function, exactly so this patch point
works — see app/api/v1/quiz.py and the same convention in tests/test_tools.py).
A tiny in-memory `_FakeSession` stands in for AsyncSession.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai import structured
from app.api.v1 import quiz as quiz_mod
from app.core.errors import NotFound, ValidationError
from app.db.models import Quiz
from app.services.scoring import (
    derive_skill_scores,
    estimate_cefr_from_score,
    grade_quiz,
    streak_days,
    weak_spots,
)

# asyncio_mode = "auto" (pyproject.toml) — plain `async def test_...` works with no marker.


# ── Test doubles ────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Just enough AsyncSession surface for quiz.py's generate/submit paths."""

    def __init__(self, get_value: Any = None, execute_value: Any = None) -> None:
        self._get_value = get_value
        self._execute_value = execute_value
        self.added: list[Any] = []
        self.committed = False

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._get_value

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._execute_value)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


def _make_user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), cefr_level="A2")


def _contains_key(obj: Any, key: str) -> bool:
    """Recursively walk a serialized response looking for `key` anywhere —
    the security property under test is "nowhere", not "not at the top level".
    """
    if isinstance(obj, dict):
        return key in obj or any(_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


# ── grade_quiz: matching rules ───────────────────────────────────────────────


def _mcq_question(expected: str = "dem") -> dict[str, Any]:
    return {
        "id": "q1",
        "type": "mcq",
        "prompt": "Ich gebe ___ Kind ein Buch.",
        "options": ["der", "dem", "den", "das"],
        "expected": expected,
        "explanation": "Dative for the indirect object.",
    }


def _cloze_question(expected: str = "Buch") -> dict[str, Any]:
    return {
        "id": "q1",
        "type": "cloze",
        "prompt": "Ich lese ein ___.",
        "options": None,
        "expected": expected,
        "explanation": "Neuter noun.",
    }


def test_grade_quiz_exact_match_is_correct() -> None:
    grade = grade_quiz([_mcq_question("dem")], [{"question_id": "q1", "value": "dem"}])
    assert grade["correct"] == 1
    assert grade["total"] == 1
    assert grade["score"] == 1.0
    assert grade["results"][0]["correct"] is True
    assert grade["results"][0]["given"] == "dem"


def test_grade_quiz_is_case_insensitive() -> None:
    grade = grade_quiz([_mcq_question("dem")], [{"question_id": "q1", "value": "DEM"}])
    assert grade["results"][0]["correct"] is True


def test_grade_quiz_trims_whitespace() -> None:
    grade = grade_quiz([_mcq_question("dem")], [{"question_id": "q1", "value": "  dem  "}])
    assert grade["results"][0]["correct"] is True


def test_grade_quiz_wrong_answer_is_marked_incorrect() -> None:
    grade = grade_quiz([_mcq_question("dem")], [{"question_id": "q1", "value": "den"}])
    assert grade["results"][0]["correct"] is False
    assert grade["correct"] == 0
    assert grade["score"] == 0.0


def test_grade_quiz_missing_answer_is_incorrect_with_given_none() -> None:
    grade = grade_quiz([_mcq_question("dem")], [])
    result = grade["results"][0]
    assert result["correct"] is False
    assert result["given"] is None
    assert result["expected"] == "dem"


def test_grade_quiz_cloze_ignores_a_leading_article_on_the_given_answer() -> None:
    grade = grade_quiz(
        [_cloze_question("Buch")], [{"question_id": "q1", "value": "das Buch"}]
    )
    assert grade["results"][0]["correct"] is True


def test_grade_quiz_cloze_ignores_a_leading_article_on_the_expected_key_too() -> None:
    grade = grade_quiz(
        [_cloze_question("das Buch")], [{"question_id": "q1", "value": "Buch"}]
    )
    assert grade["results"][0]["correct"] is True


def test_grade_quiz_score_is_fraction_correct_over_total() -> None:
    questions = [
        {**_mcq_question("dem"), "id": "q1"},
        {**_mcq_question("den"), "id": "q2"},
    ]
    answers = [
        {"question_id": "q1", "value": "dem"},
        {"question_id": "q2", "value": "dem"},  # wrong
    ]
    grade = grade_quiz(questions, answers)
    assert grade["correct"] == 1
    assert grade["total"] == 2
    assert grade["score"] == 0.5


def test_estimate_cefr_from_score_bumps_up_on_a_strong_result() -> None:
    assert estimate_cefr_from_score("A2", 0.9) == "B1"


def test_estimate_cefr_from_score_drops_on_a_weak_result() -> None:
    assert estimate_cefr_from_score("A2", 0.3) == "A1"


def test_estimate_cefr_from_score_holds_steady_in_the_middle() -> None:
    assert estimate_cefr_from_score("A2", 0.7) == "A2"


# ── POST /quiz/generate: the answer key must never reach the client ────────────


async def test_generate_response_contains_no_expected_field_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag import retriever as rag_retriever
    from app.rag.contracts import SearchResult

    async def fake_retrieve(*_a: Any, **_kw: Any) -> SearchResult:
        return SearchResult(query="dative case", strategy="dense", results=[], took_ms=1)

    monkeypatch.setattr(rag_retriever, "retrieve", fake_retrieve)

    generated = structured.GeneratedQuiz(
        topic="dative case",
        cefr_level="A2",
        questions=[
            structured.QuizQuestion(
                id="q1",
                type="cloze",
                prompt="Ich gebe ___ Kind ein Buch.",
                options=None,
                expected="dem",
                explanation="Dative for the indirect object.",
            )
        ],
        sources=None,
    )

    async def fake_generate_quiz(*_a: Any, **_kw: Any) -> structured.GeneratedQuiz:
        return generated

    monkeypatch.setattr(structured, "generate_quiz", fake_generate_quiz)

    payload = quiz_mod.QuizGenerateRequest(topic="dative case", cefr_level="A2", n=1)
    user = _make_user()
    db = _FakeSession()

    response = await quiz_mod.generate(payload, db, user)

    dumped = response.model_dump()
    assert not _contains_key(dumped, "expected")
    assert dumped["questions"][0]["prompt"] == "Ich gebe ___ Kind ein Buch."


# ── POST /quiz/submit: grading, ownership, double-submit ────────────────────────


def _persisted_quiz(user_id: uuid.UUID) -> Quiz:
    return Quiz(
        id=uuid.uuid4(),
        user_id=user_id,
        topic="dative case",
        cefr_level="A2",
        questions=[_cloze_question("dem")],
        sources=None,
        submitted_at=None,
        score=None,
    )


async def test_submit_grades_against_the_stored_answer_key() -> None:
    user = _make_user()
    stored = _persisted_quiz(user.id)
    db = _FakeSession(get_value=stored, execute_value=None)

    payload = quiz_mod.QuizSubmitRequest(
        quiz_id=stored.id, answers=[quiz_mod.QuizAnswer(question_id="q1", value="dem")]
    )
    response = await quiz_mod.submit(payload, db, user)

    assert response.score == 1.0
    assert response.correct == 1
    assert response.results[0].expected == "dem"
    assert stored.submitted_at is not None


async def test_submit_rejects_a_second_submission_of_the_same_quiz() -> None:
    user = _make_user()
    stored = _persisted_quiz(user.id)
    db = _FakeSession(get_value=stored, execute_value=None)
    payload = quiz_mod.QuizSubmitRequest(
        quiz_id=stored.id, answers=[quiz_mod.QuizAnswer(question_id="q1", value="dem")]
    )

    await quiz_mod.submit(payload, db, user)  # first submission succeeds
    with pytest.raises(ValidationError):
        await quiz_mod.submit(payload, db, user)  # second must be rejected


async def test_submit_only_the_owning_user_may_submit() -> None:
    owner = _make_user()
    stranger = _make_user()
    stored = _persisted_quiz(owner.id)
    db = _FakeSession(get_value=stored, execute_value=None)
    payload = quiz_mod.QuizSubmitRequest(
        quiz_id=stored.id, answers=[quiz_mod.QuizAnswer(question_id="q1", value="dem")]
    )

    with pytest.raises(NotFound):
        await quiz_mod.submit(payload, db, stranger)


# ── derive_skill_scores: honest about what V1 can't measure ────────────────────


def test_derive_skill_scores_has_no_listening_or_speaking_signal() -> None:
    skills = derive_skill_scores(
        quiz_accuracy=0.8, writing_overall_avg=0.75, vocab_mastered=50, vocab_total=100
    )
    assert skills["listening"] is None
    assert skills["speaking"] is None


def test_derive_skill_scores_reports_real_numbers_for_writing_and_grammar() -> None:
    skills = derive_skill_scores(
        quiz_accuracy=0.8, writing_overall_avg=0.75, vocab_mastered=50, vocab_total=100
    )
    assert skills["writing"] == 0.75
    assert skills["grammar"] == 0.8
    assert skills["reading"] == 0.8
    assert skills["vocabulary"] == 0.5


def test_derive_skill_scores_vocabulary_is_none_with_zero_total() -> None:
    skills = derive_skill_scores(
        quiz_accuracy=None, writing_overall_avg=None, vocab_mastered=0, vocab_total=0
    )
    assert skills["vocabulary"] is None
    assert skills["reading"] is None
    assert skills["grammar"] is None
    assert skills["writing"] is None


# ── weak_spots: threshold + ordering ────────────────────────────────────────────


def test_weak_spots_excludes_topics_at_or_above_the_threshold() -> None:
    stats = [SimpleNamespace(topic="dative case", attempts=10, correct=7)]  # exactly 0.7
    assert weak_spots(stats) == []


def test_weak_spots_includes_topics_below_the_threshold() -> None:
    stats = [SimpleNamespace(topic="dative case", attempts=10, correct=6)]  # 0.6 < 0.7
    result = weak_spots(stats)
    assert len(result) == 1
    assert result[0]["topic"] == "dative case"
    assert result[0]["accuracy"] == 0.6
    assert result[0]["recommendation"] == "Review Dative Case, then retry the quiz."


def test_weak_spots_orders_worst_first() -> None:
    stats = [
        SimpleNamespace(topic="accusative case", attempts=10, correct=6),  # 0.6
        SimpleNamespace(topic="dative case", attempts=10, correct=2),  # 0.2
        SimpleNamespace(topic="word order", attempts=10, correct=4),  # 0.4
    ]
    result = weak_spots(stats)
    assert [r["topic"] for r in result] == ["dative case", "word order", "accusative case"]


def test_weak_spots_skips_topics_with_zero_attempts() -> None:
    stats = [SimpleNamespace(topic="never tried", attempts=0, correct=0)]
    assert weak_spots(stats) == []


# ── streak_days ──────────────────────────────────────────────────────────────


def test_streak_days_today_only_is_one() -> None:
    today = date(2026, 7, 30)
    assert streak_days([today], today=today) == 1


def test_streak_days_three_day_run_ending_today() -> None:
    today = date(2026, 7, 30)
    days = [today, today - timedelta(days=1), today - timedelta(days=2)]
    assert streak_days(days, today=today) == 3


def test_streak_days_a_gap_breaks_the_streak() -> None:
    today = date(2026, 7, 30)
    days = [today, today - timedelta(days=2)]  # yesterday missing
    assert streak_days(days, today=today) == 1


def test_streak_days_a_run_ending_yesterday_still_counts() -> None:
    today = date(2026, 7, 30)
    yesterday = today - timedelta(days=1)
    days = [yesterday, yesterday - timedelta(days=1), yesterday - timedelta(days=2)]
    assert streak_days(days, today=today) == 3


def test_streak_days_no_activity_is_zero() -> None:
    today = date(2026, 7, 30)
    assert streak_days([], today=today) == 0


def test_streak_days_neither_today_nor_yesterday_is_zero() -> None:
    today = date(2026, 7, 30)
    days = [today - timedelta(days=5)]
    assert streak_days(days, today=today) == 0
