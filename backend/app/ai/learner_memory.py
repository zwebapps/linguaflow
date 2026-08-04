"""What the tutor remembers about a learner between conversations.

Thread history (`agent.load_history`) gives the tutor the last few turns of the
CURRENT conversation. That is short-term memory, and on its own it means every
new thread starts from nothing: the tutor greets a learner it has taught for
three months as a stranger, re-explains the case it drilled yesterday, and asks
what they're studying for every single time.

This module is the long-term half. It reads signals the app already collects —
onboarding profile, per-topic quiz accuracy, saved vocabulary, spoken-session
history — and renders them as a short block appended to the system prompt.

Two deliberate constraints:

* **Derived, never authored.** Nothing here is a separate "memory" the model
  writes to. Everything is recomputed from rows that already exist, so it
  cannot drift from the truth, needs no consistency story, and a learner
  deleting their data deletes their memory with it.
* **Small.** It rides on EVERY tutor turn, so it is capped hard. A profile that
  grows with usage would quietly turn into the most expensive part of the
  prompt and start crowding out retrieved passages.
"""

from __future__ import annotations

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SpeakingSession, TopicStat, User, Vocabulary
from app.services.scoring import weak_spots

log = structlog.get_logger(__name__)

# Caps. Chosen to stay well under a few hundred tokens in total: enough for the
# tutor to sound like it knows the learner, not enough to compete with the
# retrieved passages for room.
MAX_WEAK_TOPICS = 3
MAX_RECENT_WORDS = 12
MAX_GOAL_CHARS = 120

_GOAL_LABELS = {
    "travel": "travel",
    "work": "work and professional use",
    "exam": "an exam",
    "study": "study",
    "family": "family and relationships",
    "culture": "culture and media",
}

_STYLE_HINTS = {
    "visual": "Prefers tables, paradigms and worked examples over prose.",
    "auditory": "Prefers spoken examples; mention pronunciation and stress.",
    "reading": "Prefers written explanations and example sentences to study.",
    "kinesthetic": "Prefers doing over reading — offer a short exercise to try.",
}


async def build_learner_memory(db: AsyncSession, user: User) -> str:
    """A short profile block for the system prompt, or "" if there's nothing yet.

    Never raises. A tutor that answers without remembering the learner is worse
    than one that remembers; a tutor that 500s because a stats query failed is
    worse than both.
    """
    try:
        lines = [
            *_profile_lines(user),
            *await _weak_topic_lines(db, user),
            *await _vocabulary_lines(db, user),
            *await _speaking_lines(db, user),
        ]
    except Exception as exc:  # noqa: BLE001 — memory is an enhancement
        log.warning("learner_memory_failed", user_id=str(user.id), error=str(exc)[:200])
        return ""

    if not lines:
        return ""

    return (
        "## What you know about this learner\n"
        "Use this to stay consistent between conversations — greet them as "
        "someone you've taught before, build on what they've studied, and steer "
        "practice toward their weak areas. Do not recite this list back to them.\n"
        + "\n".join(f"- {line}" for line in lines)
    )


# ── Sections ──────────────────────────────────────────────────────────────────


def _profile_lines(user: User) -> list[str]:
    lines: list[str] = []
    if name := (user.display_name or "").strip():
        # First name only: "Hallo, Zahoor Ahmed!" reads like a form letter.
        lines.append(f"Their name is {name.split()[0]}.")
    if goal := (user.goal or "").strip():
        label = _GOAL_LABELS.get(goal.lower(), goal[:MAX_GOAL_CHARS])
        lines.append(f"They are learning for {label} — prefer examples from that setting.")
    if hint := _STYLE_HINTS.get((user.learning_style or "").lower()):
        lines.append(hint)
    return lines


async def _weak_topic_lines(db: AsyncSession, user: User) -> list[str]:
    """The topics their quiz results say they keep getting wrong.

    This is the single most useful thing the tutor can know and the one it was
    most conspicuously missing: the app has computed weak spots for the
    progress page all along, and the tutor never saw them.
    """
    rows = (
        (await db.execute(select(TopicStat).where(TopicStat.user_id == user.id)))
        .scalars()
        .all()
    )
    weak = weak_spots(rows)[:MAX_WEAK_TOPICS]
    if not weak:
        return []
    named = ", ".join(f"{w['topic']} ({round(w['accuracy'] * 100)}%)" for w in weak)
    return [f"Weakest topics by quiz accuracy: {named}. Work these in when relevant."]


async def _vocabulary_lines(db: AsyncSession, user: User) -> list[str]:
    """Words they've saved, so examples can reuse vocabulary they already own."""
    rows = (
        (
            await db.execute(
                select(Vocabulary.lemma)
                .where(
                    Vocabulary.user_id == user.id,
                    Vocabulary.language == user.target_language,
                )
                .order_by(desc(Vocabulary.created_at))
                .limit(MAX_RECENT_WORDS)
            )
        )
        .scalars()
        .all()
    )
    # SQL bounds how much is READ; the cap that matters is applied here, so it
    # holds regardless of what the query returns.
    words = list(rows)[:MAX_RECENT_WORDS]
    if not words:
        return []
    return [
        "Recently saved vocabulary: "
        + ", ".join(words)
        + ". Reuse these in examples where it fits naturally."
    ]


async def _speaking_lines(db: AsyncSession, user: User) -> list[str]:
    count = (
        await db.execute(
            select(func.count())
            .select_from(SpeakingSession)
            .where(SpeakingSession.user_id == user.id)
        )
    ).scalar_one()
    if not count:
        return []
    plural = "" if count == 1 else "s"
    return [f"They have completed {count} spoken practice session{plural}."]


def merge_into_prompt(system_prompt: str, memory: str) -> str:
    """Append the profile, keeping the prompt unchanged when there is none."""
    return f"{system_prompt}\n\n{memory}" if memory else system_prompt


__all__ = ["build_learner_memory", "merge_into_prompt"]
