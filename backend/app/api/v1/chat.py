"""AI Tutor chat endpoints — API_CONTRACT.md §2.

`POST /chat` is Server-Sent Events. The event names and their order are part of the
frontend contract, so the mapping lives in `app.ai.agent` and is asserted in tests.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.ai.agent import stream_tutor_turn
from app.core.cache import bump_quota, enforce_monthly_quota, enforce_rate_limit
from app.core.deps import CurrentUser, DbSession
from app.core.errors import NotFound, ValidationError
from app.db.models import Message, Thread

log = structlog.get_logger(__name__)
router = APIRouter()

CEFR = Literal["A1", "A2", "B1", "B2", "C1"]


# ── Schemas ───────────────────────────────────────────────────────────────────


class ChatContext(BaseModel):
    document_id: uuid.UUID | None = None
    topic: str | None = Field(default=None, max_length=200)
    cefr_level: CEFR | None = None


class ChatRequest(BaseModel):
    thread_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)
    context: ChatContext | None = None
    model_override: str | None = Field(default=None, max_length=120)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v.strip()


class ThreadSummary(BaseModel):
    id: uuid.UUID
    title: str
    message_count: int
    updated_at: Any


class ThreadPage(BaseModel):
    items: list[ThreadSummary]
    next_cursor: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _owned_thread(db: Any, user_id: uuid.UUID, thread_id: uuid.UUID) -> Thread:
    """Fetch a thread scoped to its owner. 404 (not 403) so we don't confirm existence."""
    thread = (
        await db.execute(
            select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFound("That conversation doesn't exist.")
    return thread


def _message_out(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at,
    }
    if m.role == "assistant":
        out |= {
            "model": m.model,
            "sources": m.sources or [],
            "tool_calls": m.tool_calls or [],
            "usage": m.usage or {},
        }
    return out


# ── Streaming turn ────────────────────────────────────────────────────────────


@router.post("")
async def chat(payload: ChatRequest, db: DbSession, user: CurrentUser) -> EventSourceResponse:
    """Stream one tutor turn as SSE."""
    # Cost controls before any model work happens.
    await enforce_rate_limit(str(user.id), bucket="chat")
    await enforce_monthly_quota(str(user.id))

    if payload.thread_id is not None:
        thread = await _owned_thread(db, user.id, payload.thread_id)
    else:
        thread = Thread(user_id=user.id, title="New conversation")
        db.add(thread)
        await db.commit()
        await db.refresh(thread)

    await bump_quota(str(user.id))

    async def event_source():
        try:
            async for frame in stream_tutor_turn(
                db,
                user,
                thread=thread,
                message=payload.message,
                context=payload.context.model_dump() if payload.context else None,
                model_override=payload.model_override,
            ):
                yield frame
        except Exception:
            # The stream is already open, so an exception can't become a JSON 500 —
            # it has to reach the client as an `error` frame or the UI hangs.
            log.exception("chat_stream_failed", thread_id=str(thread.id))
            yield {
                "event": "error",
                "data": {
                    "code": "internal_error",
                    "message": "The tutor stopped unexpectedly. Please try again.",
                },
            }

    # `ping` keeps proxies from idling the connection out during a long tool call.
    return EventSourceResponse(event_source(), ping=15000)


# ── Thread management ─────────────────────────────────────────────────────────


@router.get("/threads", response_model=ThreadPage)
async def list_threads(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> ThreadPage:
    counts = (
        select(Message.thread_id, func.count(Message.id).label("n"))
        .group_by(Message.thread_id)
        .subquery()
    )
    stmt = (
        select(Thread, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.thread_id == Thread.id)
        .where(Thread.user_id == user.id)
        .order_by(Thread.updated_at.desc())
        .limit(limit + 1)
    )
    if cursor:
        # Keyset pagination on updated_at — stable under inserts, unlike OFFSET.
        from datetime import datetime

        try:
            stmt = stmt.where(Thread.updated_at < datetime.fromisoformat(cursor))
        except ValueError as exc:
            raise ValidationError("Invalid cursor.") from exc

    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return ThreadPage(
        items=[
            ThreadSummary(
                id=t.id, title=t.title, message_count=int(n), updated_at=t.updated_at
            )
            for t, n in rows
        ],
        next_cursor=rows[-1][0].updated_at.isoformat() if (has_more and rows) else None,
    )


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    thread = (
        await db.execute(
            select(Thread)
            .options(selectinload(Thread.messages))
            .where(Thread.id == thread_id, Thread.user_id == user.id)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFound("That conversation doesn't exist.")

    return {
        "id": str(thread.id),
        "title": thread.title,
        "messages": [_message_out(m) for m in thread.messages],
    }


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Response:
    thread = await _owned_thread(db, user.id, thread_id)
    await db.execute(sa_delete(Thread).where(Thread.id == thread.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/threads/{thread_id}/export")
async def export_thread_endpoint(
    thread_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    format: Annotated[Literal["json", "csv", "md", "pdf"], Query()] = "json",
) -> Response:
    thread = (
        await db.execute(
            select(Thread)
            .options(selectinload(Thread.messages))
            .where(Thread.id == thread_id, Thread.user_id == user.id)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFound("That conversation doesn't exist.")

    from app.services.export import export_thread

    body, media_type, filename = export_thread(thread, format)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _content_disposition(filename: str) -> str:
    """Build an RFC 6266-safe `Content-Disposition` for a possibly-German filename.

    HTTP header values must be ASCII. Export filenames are derived from the thread
    title, which for this product is *usually* German — so an umlaut went straight
    into the header and every export (json/csv/md/pdf alike) died with
    `UnicodeDecodeError: byte 0xe4`. Send a transliterated ASCII `filename` for old
    clients plus a percent-encoded `filename*` carrying the real name.
    """
    import unicodedata
    from urllib.parse import quote

    # "Erkläre" → "Erklare": strip combining marks rather than dropping the letter,
    # so the fallback name stays readable.
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
        .replace('"', "")
        .strip()
    ) or "conversation"

    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
