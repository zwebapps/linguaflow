"""Pure scoring/analysis logic for quiz grading and the §7 analysis dashboard.

Deliberately free of DB/IO — same rationale as `app.services.srs`: these functions
take plain data (dicts, ORM rows already in memory, primitive lists) and return
plain data, so `tests/test_assessment.py` can exercise every rule without a
session, an engine, or a live LLM.

Honesty over completeness: `derive_skill_scores` returns ``None`` for
listening/speaking rather than inventing a number — V1 has no listening exercise
and no persisted pronunciation score, so pretending otherwise would mislead a
learner about their own level.
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, TypedDict

# ── Quiz grading ────────────────────────────────────────────────────────────────

# German articles carry the CASE — which is usually the exact thing a cloze is
# testing. So we must never normalise them away: stripping the article from both
# sides made "der Kind" match a key of "dem Kind", i.e. it told a learner their
# wrong dative article was right, on the one question designed to check it.
#
# The only leniency that is safe: a learner may answer with just the article when
# the key is "article + noun", because the blank often only needs the article.
# That accepts "dem" for "dem Kind" while still rejecting "der Kind".
_ARTICLES = {
    "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einen", "einem", "einer", "eines",
}

_STRIP_CHARS = string.punctuation + " \t\n\r"


class QuestionResult(TypedDict):
    question_id: str
    correct: bool
    expected: str
    given: str | None
    explanation: str


class QuizGrade(TypedDict):
    score: float
    correct: int
    total: int
    results: list[QuestionResult]


def _canonical(value: str) -> str:
    """Case-insensitive, whitespace- and punctuation-trimmed, inner space collapsed.

    Deliberately does NOT touch articles — see the note on `_ARTICLES`.
    """
    v = (value or "").strip(_STRIP_CHARS).lower()
    return " ".join(v.split())


def _split_article(value: str) -> tuple[str | None, str]:
    """→ (article, remainder). `article` is None when none is present."""
    head, _, rest = value.partition(" ")
    if rest and head in _ARTICLES:
        return head, rest.strip()
    return None, value


def _cloze_matches(given: str, expected: str) -> bool:
    """Cloze comparison: lenient about a *missing* article, strict about a *wrong* one.

    The distinction is what matters pedagogically:

    * Omission can't be proven wrong — if the key is "das Buch" and the learner
      writes "Buch", the blank may never have needed the article. Failing that is
      a frustrating false negative.
    * A **conflict** is provably wrong: key "dem Kind" vs answer "der Kind" is
      exactly the dative error the question exists to catch. Only comparing
      articles when both sides supply one keeps that strict while staying kind
      about omission.
    """
    if given == expected:
        return True

    given_art, given_noun = _split_article(given)
    exp_art, exp_noun = _split_article(expected)

    # Answering with just the (correct) article — the blank often only needs it.
    if exp_art is not None and given == exp_art:
        return True

    if given_noun != exp_noun:
        return False

    # Nouns agree. If both sides named an article, they must be the same one.
    if given_art is not None and exp_art is not None:
        return given_art == exp_art
    return True


def grade_quiz(
    questions: Sequence[Mapping[str, Any]], answers: Sequence[Mapping[str, Any]]
) -> QuizGrade:
    """Grade `answers` against the stored `questions` (each carrying `expected`).

    A question with no submitted answer counts as wrong, not skipped — `given`
    is reported as ``None`` so the client can distinguish "answered wrong" from
    "left blank".
    """
    given_by_id: dict[str, str | None] = {}
    for a in answers:
        qid = a.get("question_id")
        if qid is not None:
            given_by_id[str(qid)] = a.get("value")

    results: list[QuestionResult] = []
    correct_count = 0
    for q in questions:
        qid = str(q["id"])
        qtype = str(q.get("type") or "mcq")
        expected = str(q.get("expected") or "")
        explanation = str(q.get("explanation") or "")
        given = given_by_id.get(qid)

        if given is None:
            is_correct = False
        else:
            g, e = _canonical(given), _canonical(expected)
            is_correct = _cloze_matches(g, e) if qtype == "cloze" else g == e
        if is_correct:
            correct_count += 1

        results.append(
            QuestionResult(
                question_id=qid,
                correct=is_correct,
                expected=expected,
                given=given,
                explanation=explanation,
            )
        )

    total = len(questions)
    score = round(correct_count / total, 4) if total else 0.0
    return QuizGrade(score=score, correct=correct_count, total=total, results=results)


# ── CEFR estimate from a single quiz result ────────────────────────────────────

_LEVELS = ["A1", "A2", "B1", "B2", "C1"]


def estimate_cefr_from_score(base_level: str | None, score: float) -> str:
    """Nudge the quiz's target level up/down one step based on how well the
    learner did. This is a same-ballpark signal for the trend chart, not a full
    CEFR placement test — a strong result on an A2 quiz suggests "trending B1",
    a weak one suggests they're not solid at A2 yet.
    """
    idx = _LEVELS.index(base_level) if base_level in _LEVELS else 0
    if score >= 0.85 and idx < len(_LEVELS) - 1:
        idx += 1
    elif score < 0.5 and idx > 0:
        idx -= 1
    return _LEVELS[idx]


# ── Per-skill scores (§7 `skills`) ──────────────────────────────────────────────


def derive_skill_scores(
    *,
    quiz_accuracy: float | None,
    writing_overall_avg: float | None,
    vocab_mastered: int,
    vocab_total: int,
) -> dict[str, float | None]:
    """Map what we actually measure onto the six §7 skill keys.

    - `writing` comes straight from `WritingSubmission.scores["overall"]`, averaged.
    - `grammar` AND `reading` both come from quiz accuracy — quizzes aren't tagged
      by skill in V1, so this is a deliberate simplification, not two independent
      signals.
    - `vocabulary` is mastered/total from the SRS vocabulary list.
    - `listening` and `speaking` have no data source in V1 (no listening exercise,
      no persisted pronunciation score) — ``None``, never a fabricated number.
    """
    vocabulary = round(vocab_mastered / vocab_total, 4) if vocab_total > 0 else None
    return {
        "reading": quiz_accuracy,
        "listening": None,
        "speaking": None,
        "writing": writing_overall_avg,
        "grammar": quiz_accuracy,
        "vocabulary": vocabulary,
    }


# ── Weak spots (§7 `weak_spots`) ────────────────────────────────────────────────


def weak_spots(topic_stats: Iterable[Any], *, threshold: float = 0.7) -> list[dict[str, Any]]:
    """Topics with accuracy strictly below `threshold`, worst-first.

    Accepts anything with `.topic`/`.attempts`/`.correct` attributes (a
    `TopicStat` row, or a lightweight stand-in in tests) so this stays DB-free.
    """
    rows: list[dict[str, Any]] = []
    for ts in topic_stats:
        attempts = getattr(ts, "attempts", 0)
        correct = getattr(ts, "correct", 0)
        if attempts <= 0:
            continue
        accuracy = correct / attempts
        if accuracy < threshold:
            topic = getattr(ts, "topic", "")
            rows.append(
                {
                    "topic": topic,
                    "accuracy": round(accuracy, 4),
                    "attempts": attempts,
                    "recommendation": f"Review {topic.title()}, then retry the quiz.",
                    "document_id": None,
                }
            )
    rows.sort(key=lambda r: r["accuracy"])
    return rows


# ── Streak (§7 `counters.streak_days`) ──────────────────────────────────────────


def streak_days(days: Iterable[date], *, today: date | None = None) -> int:
    """Consecutive days of activity ending today, or ending yesterday (a streak
    doesn't die the instant midnight passes before the learner has logged in).

    A gap anywhere else breaks the count — this only ever walks backward from
    the most recent qualifying day.
    """
    day_set = set(days)
    if not day_set:
        return 0

    anchor = today
    if anchor is None or anchor not in day_set:
        if today is not None and (today - timedelta(days=1)) in day_set:
            anchor = today - timedelta(days=1)
        elif today is None:
            anchor = max(day_set)
        else:
            return 0

    streak = 0
    cursor = anchor
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
