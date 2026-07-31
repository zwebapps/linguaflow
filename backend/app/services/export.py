"""Render a chat Thread as a downloadable file (§2 `GET /chat/threads/{id}/export`).

Pure function over already-loaded ORM objects — no DB access here. `chat.py`
(owned by another track) is expected to eager-load `thread.messages` before
calling `export_thread`; this module never queries anything itself so it stays
trivially unit-testable.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Literal
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.db.models import Message, Thread

ExportFormat = Literal["json", "csv", "md", "pdf"]

_MEDIA_TYPES: dict[ExportFormat, str] = {
    "json": "application/json",
    "csv": "text/csv",
    "md": "text/markdown",
    "pdf": "application/pdf",
}


def export_thread(thread: Thread, fmt: ExportFormat) -> tuple[bytes, str, str]:
    """Return (file_bytes, media_type, filename) for `thread` in `fmt`.

    Handles a thread with zero messages without raising.
    """
    messages = list(thread.messages or [])
    filename = f"{_slug(thread.title)}.{fmt}"

    if fmt == "pdf":
        # Binary from the start — reportlab writes bytes directly, unlike the
        # three text formats below which build a `str` and get UTF-8-encoded
        # once at the bottom.
        return _to_pdf(thread, messages), _MEDIA_TYPES[fmt], filename

    if fmt == "json":
        body = _to_json(thread, messages)
    elif fmt == "csv":
        body = _to_csv(messages)
    elif fmt == "md":
        body = _to_md(thread, messages)
    else:  # pragma: no cover - callers validate `fmt` against the Literal via Pydantic
        raise ValueError(f"unsupported export format: {fmt!r}")

    return body.encode("utf-8"), _MEDIA_TYPES[fmt], filename


def _slug(title: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in (title or "thread").lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "thread"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _to_json(thread: Thread, messages: list[Message]) -> str:
    payload = {
        "id": str(thread.id) if thread.id else None,
        "title": thread.title,
        "created_at": _iso(thread.created_at),
        "messages": [
            {
                "id": str(m.id) if m.id else None,
                "role": m.role,
                "content": m.content,
                "model": m.model,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _to_csv(messages: list[Message]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "role", "content", "model", "created_at"])
    for m in messages:
        writer.writerow(
            [str(m.id) if m.id else "", m.role, m.content, m.model or "", _iso(m.created_at) or ""]
        )
    return buf.getvalue()


def _to_md(thread: Thread, messages: list[Message]) -> str:
    lines = [f"# {thread.title}", ""]
    if not messages:
        lines.append("_No messages yet._")
        return "\n".join(lines) + "\n"
    for m in messages:
        who = "**You**" if m.role == "user" else "**Tutor**"
        stamp = _iso(m.created_at) or ""
        lines.append(f"{who} ({stamp}):" if stamp else f"{who}:")
        lines.append("")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── PDF ───────────────────────────────────────────────────────────────────────
#
# reportlab's built-in Helvetica/Helvetica-Bold/Helvetica-Oblique base fonts use
# WinAnsiEncoding (Latin-1), which covers ä/ö/ü/ß natively — no TTF embedding
# needed for German. Paragraph text goes through a mini XML parser though, so
# it must be escaped for `&`/`<`/`>` first (`_escape_for_pdf`), same reason
# you'd escape user content before dropping it into HTML.
_PDF_PAGE_MARGIN = 20 * mm


def _escape_for_pdf(text: str) -> str:
    """Escape for reportlab's Paragraph mini-XML, then turn newlines into
    `<br/>` — the one piece of that markup we deliberately use, so multi-line
    learner/tutor turns keep their line breaks instead of running together.
    """
    return _xml_escape(text or "").replace("\n", "<br/>")


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ExportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18,
        ),
        "meta": ParagraphStyle(
            "ExportMeta",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=HexColor("#555555"),
            spaceAfter=4,
        ),
        "speaker": ParagraphStyle(
            "ExportSpeaker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            spaceBefore=12,
            spaceAfter=3,
        ),
        # `leading` (line height) set explicitly so long, wrapped messages
        # stay readable instead of reportlab's tighter single-spaced default.
        "body": ParagraphStyle(
            "ExportBody", parent=base["Normal"], fontName="Helvetica", fontSize=10, leading=14,
        ),
        "small": ParagraphStyle(
            "ExportSmall",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            textColor=HexColor("#888888"),
            spaceBefore=2,
        ),
        "empty": ParagraphStyle(
            "ExportEmpty", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=10,
        ),
    }


def _to_pdf(thread: Thread, messages: list[Message]) -> bytes:
    """Render a readable transcript: title, generated-at, then each turn
    labelled Learner/Tutor. `SimpleDocTemplate` + `Paragraph` flow content
    across as many pages as it needs — long messages wrap and paginate for
    free, we never lay out text by hand or clip a page.
    """
    styles = _pdf_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=_PDF_PAGE_MARGIN,
        bottomMargin=_PDF_PAGE_MARGIN,
        leftMargin=_PDF_PAGE_MARGIN,
        rightMargin=_PDF_PAGE_MARGIN,
        title=thread.title or "Conversation",
    )

    story: list[Any] = [
        Paragraph(_escape_for_pdf(thread.title or "Conversation"), styles["title"]),
        Paragraph(f"Generated {_iso(datetime.utcnow())}", styles["meta"]),
        Spacer(1, 6 * mm),
    ]

    if not messages:
        story.append(Paragraph("No messages yet.", styles["empty"]))
    else:
        for m in messages:
            who = "Learner" if m.role == "user" else "Tutor"
            stamp = _iso(m.created_at) or ""
            label = f"{who} ({stamp})" if stamp else who
            story.append(Paragraph(_escape_for_pdf(label), styles["speaker"]))
            story.append(Paragraph(_escape_for_pdf(m.content), styles["body"]))

            if m.role == "assistant":
                usage = m.usage or {}
                cost = usage.get("cost_usd")
                bits = []
                if m.model:
                    bits.append(f"model: {m.model}")
                if isinstance(cost, (int, float)):
                    bits.append(f"cost: ${cost:.4f}")
                if bits:
                    story.append(Paragraph(_escape_for_pdf(" · ".join(bits)), styles["small"]))

    doc.build(story)
    return buf.getvalue()
