"""Outbound email — a seam, not a provider.

V1 ships exactly one sink: "console", which logs the message and writes it to
`var/outbox/<timestamp>-<slug>.txt` so a developer can open the file and click
the verification link. That is deliberate: the app must be fully exercisable
(signup → verify → banner clears) with zero external credentials. Wiring a
real provider (SMTP, Resend, SES…) means adding a sink here and flipping
`EMAIL_SINK` — callers never change.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

OUTBOX_DIR = Path("var/outbox")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "mail"


async def send_email(*, to: str, subject: str, text: str) -> None:
    """Deliver one plain-text email through the configured sink.

    Never raises on delivery problems — a failed verification email must not
    fail the signup that triggered it; the learner can hit "resend".
    """
    try:
        if settings.EMAIL_SINK == "console":
            log.info("email_console_sink", to=to, subject=subject, body=text)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            path = OUTBOX_DIR / f"{stamp}-{_slug(subject)}.txt"
            content = f"To: {to}\nSubject: {subject}\n\n{text}\n"
            await asyncio.to_thread(OUTBOX_DIR.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, "utf-8")
    except Exception as exc:  # noqa: BLE001 — see docstring
        log.warning("email_send_failed", to=to, subject=subject, error=str(exc))
