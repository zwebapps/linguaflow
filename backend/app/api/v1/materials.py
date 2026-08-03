"""Learning materials — vocabulary lists, grammar notes, books, sentence banks.

Mounted at `/materials`, so paths here are relative.

Distinct from `/library`, and the difference matters: `/library` lists documents
already ingested into THIS platform (chunked, embedded, readable in Reading
Mode). `/materials` lists openly-licensed sources out in the world that a learner
can study directly or that an admin can pull in. One is our corpus; the other is
a reading list.

Every response carries the licence and the credit line, because half of these are
CC BY-SA and attribution is a condition of use, not a footnote. The client cannot
render a compliant page without those fields, so the API refuses to omit them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.ai.languages import TARGET_LANGUAGES
from app.content import catalogue as cat
from app.content import gutenberg
from app.core.deps import CurrentUser
from app.core.errors import NotFound

router = APIRouter()

MaterialKind = Literal["vocabulary", "grammar", "reader", "book", "sentences"]


# ── Schemas ────────────────────────────────────────────────────────────────────


class LicenceOut(BaseModel):
    code: str
    name: str
    url: str
    requires_attribution: bool
    share_alike: bool


class MaterialOut(BaseModel):
    id: str
    language: str
    kind: str
    title: str
    description: str
    url: str
    cefr_level: str | None
    licence: LicenceOut
    attribution: str


class MaterialsPage(BaseModel):
    language: str
    items: list[MaterialOut]


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    language: str
    download_url: str
    source_type: str
    subjects: list[str]
    # Public domain has no attribution requirement, but crediting Gutenberg is
    # both courteous and useful — a learner may want to browse there directly.
    licence: LicenceOut
    attribution: str


class BooksPage(BaseModel):
    language: str
    items: list[BookOut]


# ── Mapping ────────────────────────────────────────────────────────────────────


def _licence_out(code: str) -> LicenceOut:
    lic = cat.LICENCES[code]
    return LicenceOut(
        code=lic.code,
        name=lic.name,
        url=lic.url,
        requires_attribution=lic.requires_attribution,
        share_alike=lic.share_alike,
    )


def _material_out(m: cat.Material) -> MaterialOut:
    return MaterialOut(
        id=m.id,
        language=m.language,
        kind=m.kind,
        title=m.title,
        description=m.description,
        url=m.url,
        cefr_level=m.cefr_level,
        licence=_licence_out(m.licence),
        attribution=m.attribution,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_materials(
    user: CurrentUser,
    # Defaults to what the learner is studying, overridable so they can look
    # ahead at a language before switching to it.
    language: Annotated[str | None, Query(max_length=5)] = None,
    kind: Annotated[MaterialKind | None, Query()] = None,
    level: Annotated[str | None, Query(max_length=2)] = None,
) -> MaterialsPage:
    lang = (language or user.target_language).lower()
    items = cat.materials_for(lang, kind=kind, cefr_level=level)
    return MaterialsPage(language=lang, items=[_material_out(m) for m in items])


@router.get("/languages")
async def languages_with_materials(user: CurrentUser) -> dict[str, list[dict[str, object]]]:
    """Which languages have a materials pack, and whether we teach them yet.

    `teachable` is surfaced rather than filtered on: a learner may legitimately
    want the reading list for a language whose grammar engine is not finished,
    and hiding it would be less honest than labelling it.
    """
    del user  # auth only — the catalogue is not per-user
    out = []
    for code in cat.languages_with_materials():
        tgt = TARGET_LANGUAGES.get(code)
        out.append(
            {
                "code": code,
                "name": tgt.name if tgt else code,
                "endonym": tgt.endonym if tgt else code,
                "teachable": bool(tgt and tgt.fully_supported),
                "material_count": len(cat.materials_for(code)),
            }
        )
    return {"languages": out}


@router.get("/books")
async def list_books(
    user: CurrentUser,
    language: Annotated[str | None, Query(max_length=5)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> BooksPage:
    """Public-domain books a learner can read now.

    Live from Gutendex rather than a stored list, so the shelf tracks Gutenberg
    as it grows. A fetch failure yields an empty shelf, not a 502 — the other
    materials on the page are unaffected and should still render.
    """
    lang = (language or user.target_language).lower()
    books = await gutenberg.popular(lang, limit=limit)
    return BooksPage(
        language=lang,
        items=[
            BookOut(
                id=b.gutenberg_id,
                title=b.title,
                author=b.byline,
                language=b.language,
                download_url=b.download_url,
                source_type=b.source_type,
                subjects=b.subjects,
                licence=_licence_out("public-domain"),
                attribution="Project Gutenberg",
            )
            for b in books
        ],
    )


@router.get("/{material_id}")
async def get_material(material_id: str, user: CurrentUser) -> MaterialOut:
    del user  # auth only
    found = cat.find(material_id)
    if found is None:
        raise NotFound("No such material.")
    return _material_out(found)
