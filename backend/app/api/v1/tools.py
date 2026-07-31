"""Direct tool endpoints — API_CONTRACT.md §3.

The tutor calls these same capabilities autonomously via `app.ai.tools.registry`
during a chat turn; these routes let Reading Mode (tap-a-word), the verb-drill
screen, and Global Search invoke the identical logic directly, without paying
for a full chat turn. Validation patterns mirror `registry.py`'s frozen §11
rules so a lemma/verb the tutor would accept is accepted here too.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app.ai.tools import dictionary
from app.ai.tools.conjugation import Tense, conjugate
from app.core.cache import bump_quota, enforce_monthly_quota, enforce_rate_limit
from app.core.deps import CurrentUser, DbSession
from app.core.errors import ValidationError
from app.rag import retriever as rag_retriever

log = structlog.get_logger(__name__)
router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]

# Mirrors app/ai/tools/registry.py's _LEMMA_PATTERN / _VERB_PATTERN exactly — a
# word the agent's tool-calling loop would accept must be accepted here too.
_LEMMA_PATTERN = r"^[A-Za-zÄÖÜäöüß-]{1,64}$"
_VERB_PATTERN = r"^[A-Za-zÄÖÜäöüß-]{1,48}$"


# ── Schemas ───────────────────────────────────────────────────────────────────


class LookupWordRequest(BaseModel):
    lemma: str = Field(pattern=_LEMMA_PATTERN)
    # Bounded: these are joined into the LLM prompt on a curated-table miss, so an
    # unbounded list let one request carry a megabyte-scale prompt.
    gloss_langs: list[Annotated[str, StringConstraints(min_length=2, max_length=8)]] | None = (
        Field(default=None, max_length=5)
    )


class MeaningOut(BaseModel):
    lang: str
    text: str


class ExampleOut(BaseModel):
    de: str
    en: str


class LookupWordResponse(BaseModel):
    lemma: str
    pos: str | None = None
    article: str | None = None
    plural: str | None = None
    ipa: str | None = None
    audio_url: str
    meanings: list[MeaningOut]
    examples: list[ExampleOut]
    cefr_level: str | None = None
    source: Literal["dictionary", "llm"]


class ConjugateRequest(BaseModel):
    verb: str = Field(pattern=_VERB_PATTERN)
    tense: Tense


class ConjugateResponse(BaseModel):
    verb: str
    tense: str
    is_irregular: bool
    auxiliary: str
    forms: dict[str, str]
    source: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    cefr_level: CEFR | None = None
    skill: str | None = Field(default=None, max_length=30)
    k: int = Field(default=6, ge=1, le=20)


class SearchResultOut(BaseModel):
    id: str
    document_id: str
    title: str
    snippet: str
    score: float
    dense_score: float | None
    keyword_score: float | None
    page: int | None
    url: str | None


class SearchResponse(BaseModel):
    query: str
    strategy: str
    results: list[SearchResultOut]
    took_ms: int


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/lookup-word", response_model=LookupWordResponse)
async def lookup_word(
    payload: LookupWordRequest, db: DbSession, user: CurrentUser
) -> LookupWordResponse:
    # A curated-table miss falls through to a real billed LLM call (see
    # dictionary.py), so this needs the monthly quota too — enforcing only the
    # per-minute limit made this route a way to keep spending after the cap was
    # reached, unlike /chat, /quiz, /writing and /speaking which all count.
    await enforce_rate_limit(str(user.id), bucket="tools")
    await enforce_monthly_quota(str(user.id))

    # No explicit request -> the learner's own languages. A Turkish learner
    # tapping a word in the reader should see "masa", not only "table".
    if payload.gloss_langs:
        gloss_langs = tuple(payload.gloss_langs)
    else:
        native = getattr(user, "native_language", None) or "en"
        profile = tuple(user.gloss_langs or ())
        seen: list[str] = []
        for lang in (native, *profile, "en"):
            if lang not in seen:
                seen.append(lang)
        gloss_langs = tuple(seen)
    result = await dictionary.lookup(db, payload.lemma, gloss_langs=gloss_langs, user_id=user.id)
    # Only a genuine LLM fallback consumes allowance; a curated hit is free.
    if result.get("source") == "llm":
        await bump_quota(str(user.id))
    return LookupWordResponse(**result)


@router.post("/conjugate", response_model=ConjugateResponse)
async def conjugate_verb(payload: ConjugateRequest, user: CurrentUser) -> ConjugateResponse:
    await enforce_rate_limit(str(user.id), bucket="tools")

    try:
        result = conjugate(payload.verb, payload.tense)
    except ValueError as exc:
        # conjugate() raises for anything that isn't a plausible -en/-n infinitive —
        # surface that as the same 422 envelope every other bad input gets, with
        # the engine's own explanation as the message.
        raise ValidationError(str(exc)) from exc

    return ConjugateResponse(
        verb=result["verb"],
        tense=result["tense"],
        is_irregular=result["is_irregular"],
        auxiliary=result["auxiliary"],
        forms=result["forms"],
        source=result["source"],
    )


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, db: DbSession, user: CurrentUser) -> SearchResponse:
    await enforce_rate_limit(str(user.id), bucket="tools")

    result = await rag_retriever.retrieve(
        db, payload.query, cefr_level=payload.cefr_level, skill=payload.skill, k=payload.k
    )
    return SearchResponse(
        query=result.query,
        strategy=result.strategy,
        # Built field-by-field (not `**asdict(chunk)`) so `text`/`cefr_level` —
        # internal RetrievedChunk fields the contract doesn't list — never leak.
        results=[
            SearchResultOut(
                id=c.id,
                document_id=c.document_id,
                title=c.title,
                snippet=c.snippet,
                score=round(c.score, 4),
                dense_score=c.dense_score,
                keyword_score=c.keyword_score,
                page=c.page,
                url=c.url,
            )
            for c in result.results
        ],
        took_ms=result.took_ms,
    )
