"""The SSE **wire format** — asserted over real HTTP, not on the generator.

Why this file exists: `sse_starlette` renders a non-string `data` with `str()`,
which emits a Python dict repr (`{'a': 1}`) that `JSON.parse()` rejects. Every
generator-level test passed while the actual bytes on the wire were unparseable
by the browser. Testing the serialised output is the only way to catch that class
of bug, so it gets its own file.
"""

from __future__ import annotations

import json

import pytest


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body the way a browser client does — strict JSON per frame.

    Normalises CRLF first: the server emits spec-compliant `\\r\\n` line endings,
    so splitting naively on `\\n\\n` finds a single giant block and silently
    reports one frame instead of failing loudly.
    """
    body = body.replace("\r\n", "\n")
    frames: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event and data:
            # Strict: single-quoted Python reprs raise here, which is the point.
            frames.append((event, json.loads(data)))
    return frames


def test_parser_accepts_json_frames() -> None:
    body = 'event: start\ndata: {"thread_id": "abc", "model": "m"}\n\n'
    assert parse_sse(body) == [("start", {"thread_id": "abc", "model": "m"})]


def test_parser_rejects_a_python_dict_repr() -> None:
    """Pins the exact failure mode: this is what the bug put on the wire."""
    body = "event: start\ndata: {'thread_id': 'abc', 'model': 'm'}\n\n"
    with pytest.raises(json.JSONDecodeError):
        parse_sse(body)


def test_agent_sse_helper_emits_parseable_json() -> None:
    from app.ai.agent import _sse

    frame = _sse("tool_call", {"id": "c1", "name": "conjugate_verb", "args": {"verb": "gehen"}})
    assert isinstance(frame["data"], str)
    assert json.loads(frame["data"])["args"] == {"verb": "gehen"}


def test_speaking_sse_helper_emits_parseable_json() -> None:
    from app.api.v1.speaking import _sse

    frame = _sse("transcript", {"text": "Guten Tag", "duration_s": None})
    assert isinstance(frame["data"], str)
    assert json.loads(frame["data"])["text"] == "Guten Tag"


def test_umlauts_survive_serialisation() -> None:
    """German text must round-trip — `ensure_ascii=False` keeps it readable."""
    from app.ai.agent import _sse

    frame = _sse("token", {"text": "Ich möchte ein Stück Kuchen — größer!"})
    assert json.loads(frame["data"])["text"] == "Ich möchte ein Stück Kuchen — größer!"


def test_non_json_native_values_do_not_break_the_frame() -> None:
    """UUIDs/datetimes appear in payloads; `default=str` must keep them serialisable."""
    import uuid
    from datetime import UTC, datetime

    from app.ai.agent import _sse

    frame = _sse("done", {"message_id": uuid.uuid4(), "at": datetime.now(UTC)})
    parsed = json.loads(frame["data"])
    assert isinstance(parsed["message_id"], str)
    assert isinstance(parsed["at"], str)
