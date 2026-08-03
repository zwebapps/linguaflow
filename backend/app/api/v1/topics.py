"""Learning topics — the per-level syllabus behind the "pick a topic" dropdowns.

Mounted at `/topics`. Read-only: the registry lives in code
(`app.content.topics`), not the database, because a syllabus changes at the
cadence of a curriculum review, not of user traffic.

Defaults mirror `/materials`: no parameters means "the learner's own target
language at the learner's own level" — the level a learner selected in their
profile is the level they study at, everywhere, unless they explicitly look
ahead with `?level=`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.content import topics as reg
from app.core.deps import CurrentUser

router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]


class TopicOut(BaseModel):
    id: str
    level: str
    kind: str
    title: str
    title_en: str


class TopicsPage(BaseModel):
    language: str
    level: str
    items: list[TopicOut]


@router.get("")
async def list_topics(
    user: CurrentUser,
    level: Annotated[CEFR | None, Query()] = None,
    language: Annotated[str | None, Query(max_length=5)] = None,
) -> TopicsPage:
    lang = (language or user.target_language).lower()
    lvl = level or user.cefr_level
    items = reg.topics_for(lang, lvl)
    return TopicsPage(
        language=lang,
        level=lvl,
        items=[
            TopicOut(id=t.id, level=t.level, kind=t.kind, title=t.title, title_en=t.title_en)
            for t in items
        ],
    )
