"""Pure SM-2-style spaced-repetition scheduler.

Deliberately free of DB/IO: it takes an ORM ``Flashcard`` instance already in
memory and mutates it, so it is trivial to unit test (see
``tests/test_auth_srs.py``) and trivial to call from ``flashcards.py`` inside
an existing session/transaction without this module knowing sessions exist.

Interval design (why these numbers, not classic SM-2's raw two-state model):
  * Classic SM-2 only distinguishes "recalled / not recalled". A vocab app
    benefits from the four-grade UX (Anki-style) so a *correct but slow*
    answer doesn't get the same fat interval jump as an *instant, easy* one.
  * ``_LADDER`` gives each success grade its own two-step "learning" ramp
    (day 1, day 2) before the review graduates to ease-based scaling. "hard"
    ramps slower (1 → 3 days) than "good" (1 → 6, the SM-2 textbook default)
    than "easy" (2 → 10) — this mirrors Anki's default learning steps.
  * Once a card is past the ladder, the next interval is
    ``interval * ease * grade_multiplier`` — the standard SM-2 formula, with
    a small per-grade multiplier so "hard" still grows (never stalls a card
    forever) but slower than "good", and "easy" pulls ahead.
  * ``again`` is a lapse, not just a low grade: it always drops the card back
    to a 0-day interval and a short (10-minute) re-review, and increments
    ``lapses`` — the SM-2 "relearning queue" behaviour. It demotes status to
    "learning" even from "mastered", because a lapse means the item wasn't
    actually retained.
  * ``status`` is not a column on ``Flashcard`` (it lives on the linked
    ``Vocabulary`` row, which is what ``GET /vocab?status=`` filters on) —
    so this function updates ``card.vocabulary.status`` when the
    relationship is loaded, and simply skips that step otherwise. Callers
    that care about the status transition (the flashcards grade endpoint)
    must eager-load ``Flashcard.vocabulary`` before calling this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.db.models import Flashcard

Grade = Literal["again", "hard", "good", "easy"]

# (first-success-interval, second-success-interval) in days, before ease-based
# scaling takes over. Only used while interval_days hasn't yet passed the
# second step.
_LADDER: dict[Grade, tuple[int, int]] = {
    "hard": (1, 3),
    "good": (1, 6),
    "easy": (2, 10),
}

# Multiplier applied on top of `ease` once a card is past the ladder.
_EASE_MULTIPLIER: dict[Grade, float] = {"hard": 0.85, "good": 1.0, "easy": 1.3}

# How much a grade nudges the card's ease factor (SM-2's "E-Factor").
_EASE_DELTA: dict[Grade, float] = {"again": -0.3, "hard": -0.15, "good": 0.0, "easy": 0.15}
_MIN_EASE = 1.3
_MAX_EASE = 3.0

# "again" doesn't wait a full day — it's a short-term re-review, not a real
# scheduling interval, so it isn't expressed in `interval_days` (stays 0).
_AGAIN_RETRY_MINUTES = 10

# A card graduates from "learning" to "mastered" once its interval reaches
# this many days (roughly "reviewed successfully for three weeks running").
_MASTERED_AT_DAYS = 21

# Ceiling so a long streak of "easy" grades can't compound past a sane review
# horizon (and, mechanically, can't overflow `datetime` when added to `now`).
_MAX_INTERVAL_DAYS = 1825  # ~5 years


def grade_card(card: Flashcard, grade: Grade) -> Flashcard:
    """Apply one review outcome to `card` in place and return it.

    Mutates: ease, interval_days, reps, lapses, due_at, last_grade, and (via
    the loaded relationship) the linked Vocabulary's status.
    """
    now = datetime.now(UTC)
    card.reps += 1
    card.last_grade = grade
    card.ease = round(max(_MIN_EASE, min(_MAX_EASE, card.ease + _EASE_DELTA[grade])), 2)

    if grade == "again":
        card.lapses += 1
        card.interval_days = 0
        card.due_at = now + timedelta(minutes=_AGAIN_RETRY_MINUTES)
        _set_status(card, "learning")
        return card

    day1, day2 = _LADDER[grade]
    if card.interval_days <= 0:
        # Brand new (or just lapsed) — start on this grade's first learning step.
        next_days = day1
    elif card.interval_days <= day1:
        # Still inside the learning ramp: take the second step.
        next_days = day2
    else:
        # Graduated → ease-based scaling.
        #
        # The comparison here MUST be against `day1`, not `day2`. Testing
        # `interval < day2` meant a card already further along than one grade's
        # ladder got yanked back onto it: at 9 days, "easy" (day2=10) returned 10
        # while "good" (day2=6) multiplied up to 22 — so rating a card *easier*
        # made it come back *sooner*, and "easy" could never reach `mastered`.
        # Multiplying once past day1 keeps intervals monotonic in grade, because
        # _EASE_MULTIPLIER is ordered hard < good < easy.
        next_days = min(
            _MAX_INTERVAL_DAYS,
            max(1, round(card.interval_days * card.ease * _EASE_MULTIPLIER[grade])),
        )

    card.interval_days = next_days
    card.due_at = now + timedelta(days=next_days)
    _set_status(card, "mastered" if next_days >= _MASTERED_AT_DAYS else "learning")
    return card


def _set_status(card: Flashcard, status: Literal["learning", "mastered"]) -> None:
    """Best-effort: only touches the linked Vocabulary if it's already loaded.

    Never triggers a lazy load — in an async SQLAlchemy session that would
    raise (or deadlock) instead of quietly fetching, and this module must
    stay IO-free to be unit-testable without a DB.
    """
    vocab = card.__dict__.get("vocabulary")
    if vocab is not None:
        vocab.status = status
