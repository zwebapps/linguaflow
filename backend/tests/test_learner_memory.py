"""What the tutor carries between conversations.

Thread history covers the current conversation. This is the other half: the
tutor knowing who it is teaching. Without it a learner of three months is
greeted as a stranger in every new thread and re-taught the case they drilled
yesterday.

The block rides on EVERY turn, so the size caps here are load-bearing, not
housekeeping — an uncapped profile grows with usage until it crowds out the
retrieved passages it sits next to.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.ai import learner_memory as lm


class _User:
    def __init__(self, **kw: Any) -> None:
        self.id = uuid.uuid4()
        self.display_name = kw.get("display_name")
        self.goal = kw.get("goal")
        self.learning_style = kw.get("learning_style")
        self.target_language = kw.get("target_language", "de")


class _Stat:
    def __init__(self, topic: str, attempts: int, correct: int) -> None:
        self.topic, self.attempts, self.correct = topic, attempts, correct


class _Session:
    """Serves each of the three queries in the order the builder makes them."""

    def __init__(self, stats=None, words=None, sessions: int = 0) -> None:
        self._returns: list[Any] = [stats or [], words or [], sessions]

    async def execute(self, _stmt: Any) -> Any:
        value = self._returns.pop(0)
        return _Result(value)


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return self._value

    def scalar_one(self):
        return self._value


async def build(**kw: Any) -> str:
    session = _Session(
        stats=kw.pop("stats", None),
        words=kw.pop("words", None),
        sessions=kw.pop("sessions", 0),
    )
    return await lm.build_learner_memory(session, _User(**kw))


# ── Nothing to remember ───────────────────────────────────────────────────────


async def test_a_brand_new_learner_adds_nothing_to_the_prompt() -> None:
    """An empty "what you know" heading is worse than none — it invites the
    model to invent a history."""
    assert await build() == ""


def test_an_empty_profile_leaves_the_prompt_byte_identical() -> None:
    assert lm.merge_into_prompt("SYSTEM", "") == "SYSTEM"


# ── The profile ───────────────────────────────────────────────────────────────


async def test_the_learner_is_addressed_by_first_name() -> None:
    """"Hallo, Zahoor Ahmed!" reads like a form letter."""
    out = await build(display_name="Zahoor Ahmed")
    assert "Zahoor" in out and "Ahmed" not in out


async def test_why_they_are_learning_reaches_the_tutor() -> None:
    assert "travel" in await build(goal="travel")


async def test_an_unknown_goal_is_passed_through_rather_than_dropped() -> None:
    """Onboarding can add a goal the label map hasn't caught up with."""
    assert "medical school" in await build(goal="medical school")


async def test_learning_style_becomes_an_instruction_not_a_label() -> None:
    """"visual" tells the model nothing; "prefers tables" changes the answer."""
    out = await build(learning_style="visual")
    assert "table" in out.lower()


# ── Weak spots ────────────────────────────────────────────────────────────────


async def test_topics_they_keep_getting_wrong_are_surfaced() -> None:
    """The app computed these for the progress page all along; the tutor was
    the one place that never saw them."""
    out = await build(stats=[_Stat("dative case", attempts=10, correct=3)])
    assert "dative case" in out and "30%" in out


async def test_a_topic_they_are_good_at_is_not_flagged_as_weak() -> None:
    out = await build(stats=[_Stat("plurals", attempts=10, correct=10)])
    assert "plurals" not in out


async def test_only_the_worst_few_topics_are_listed() -> None:
    stats = [_Stat(f"weakspot{i}", attempts=10, correct=i) for i in range(8)]
    out = await build(stats=stats)
    assert out.count("weakspot") == lm.MAX_WEAK_TOPICS
    assert "weakspot0" in out, "the worst one must always make the cut"


# ── Vocabulary ────────────────────────────────────────────────────────────────


async def test_saved_words_are_offered_back_for_reuse() -> None:
    out = await build(words=["der Tisch", "schlendern"])
    assert "der Tisch" in out and "schlendern" in out


async def test_the_word_list_is_capped() -> None:
    """A learner with 500 saved words must not send 500 words per turn."""
    out = await build(words=[f"wort{i}" for i in range(lm.MAX_RECENT_WORDS + 40)])
    assert out.count("wort") == lm.MAX_RECENT_WORDS


# ── Speaking ──────────────────────────────────────────────────────────────────


async def test_spoken_practice_is_counted_and_reads_naturally() -> None:
    assert "1 spoken practice session." in await build(sessions=1)
    assert "7 spoken practice sessions" in await build(sessions=7)


# ── Failure ───────────────────────────────────────────────────────────────────


async def test_a_failing_query_costs_the_memory_not_the_answer() -> None:
    """Memory is an enhancement. A tutor that answers without it beats one that
    500s because a stats query broke."""

    class _Broken:
        async def execute(self, _stmt: Any) -> Any:
            raise RuntimeError("connection reset")

    assert await lm.build_learner_memory(_Broken(), _User(display_name="Ana")) == ""


# ── Instructions to the model ─────────────────────────────────────────────────


async def test_the_model_is_told_not_to_read_the_profile_aloud() -> None:
    """Without this the first reply of every thread is a summary of the
    learner's own statistics back at them."""
    out = await build(display_name="Ana", sessions=3)
    assert "not recite" in out.lower() or "do not recite" in out.lower()
