"""Our domain tools, exposed as an MCP server over stdio.

Any MCP client — Claude Desktop, an IDE, another agent — can connect to this
process and call `conjugate_verb`, `lookup_german_word`, `search_knowledge_base`,
and `german_examples` exactly like the tutor agent's own LangChain tools
(`app.ai.tools.registry`), just over the MCP wire protocol instead of an in-process
call.

Run standalone:

    python -m app.mcp.server

Claude Desktop / any stdio-based MCP client config (``claude_desktop_config.json``
or equivalent)::

    {
      "mcpServers": {
        "linguaflow": {
          "command": "/absolute/path/to/backend/.venv/bin/python",
          "args": ["-m", "app.mcp.server"]
        }
      }
    }

Built on `mcp.server.mcpserver.MCPServer` (the ergonomic wrapper in `mcp` v2 —
this SDK renamed the old v1 `FastMCP` class; there is no
`mcp.server.fastmcp` module in this version, verified against
`.venv/lib/python3.11/site-packages/mcp/`). `@server.tool()` derives the JSON
schema straight from each function's type hints, so no manual schema authoring
is needed.

Error handling: every tool below catches its own domain exceptions and returns a
descriptive string, matching the voice of `app.ai.tools.registry` (never raise
into the model-facing result). `MCPServer` also wraps any *unexpected* exception
into an `isError` `CallToolResult` at the transport layer
(`mcp/server/mcpserver/server.py:_handle_call_tool`) — so a bug here degrades to
one failed tool call, never a crashed server loop.
"""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.mcpserver import MCPServer

from app.ai.tools.conjugation import Tense, conjugate
from app.db.session import SessionLocal
from app.mcp import german_data
from app.rag import retriever as rag_retriever

log = structlog.get_logger(__name__)

server = MCPServer(
    "linguaflow-ai",
    title="LinguaFlow AI tools",
    instructions=(
        "Tools for German-language tutoring: deterministic verb conjugation, "
        "Wiktionary-sourced word lookup, the course knowledge-base search, and "
        "real example sentences from Tatoeba."
    ),
)


@server.tool(
    description=(
        "Conjugate a German verb, given in its infinitive form, into a specific tense "
        "(praesens, praeteritum, perfekt, futur1, konjunktiv2, imperativ). Always use "
        "this instead of producing a conjugation from memory — it is computed by a "
        "deterministic rule engine, never guessed."
    )
)
async def conjugate_verb(verb: str, tense: Tense = "praesens") -> dict[str, Any] | str:
    try:
        return dict(conjugate(verb, tense))
    except ValueError as exc:
        # conjugate() raises for anything that isn't a plausible -en/-n infinitive.
        return f"'{verb}' doesn't look like a German infinitive: {exc}"
    except Exception as exc:
        log.warning("mcp_conjugate_verb_failed", verb=verb, tense=tense, error=str(exc))
        return f"Couldn't conjugate '{verb}' right now."


@server.tool(
    description=(
        "Look up a German word in Wiktionary: part of speech, grammatical gender "
        "(as der/die/das), plural, and IPA pronunciation. Sourced from Wiktionary's "
        "structured entries rather than generated, so it is authoritative for exactly "
        "the fact — noun gender — an LLM is most likely to get wrong with confidence."
    )
)
async def lookup_german_word(lemma: str) -> dict[str, Any] | str:
    try:
        result = await german_data.lookup_word(lemma)
    except Exception as exc:
        log.warning("mcp_lookup_german_word_failed", lemma=lemma, error=str(exc))
        return f"Couldn't look up '{lemma}' right now."
    if not result:
        return f"No Wiktionary entry found for '{lemma}'."
    return result


@server.tool(
    description=(
        "Search the German-learning knowledge base (grammar notes, stories, lesson "
        "content) for passages relevant to a question. Optionally filter by CEFR "
        "level (A1-C1) and cap the number of results with k."
    )
)
async def search_knowledge_base(
    query: str, cefr_level: str | None = None, k: int | None = None
) -> dict[str, Any] | str:
    try:
        # One session per call, opened and closed here — this process has no
        # FastAPI request lifecycle to hang a session off of.
        async with SessionLocal() as db:
            result = await rag_retriever.retrieve(db, query, cefr_level=cefr_level, k=k)
    except Exception as exc:
        log.warning("mcp_search_knowledge_base_failed", query=query, error=str(exc))
        return "The knowledge base search is unavailable right now."
    return {
        "query": result.query,
        "strategy": result.strategy,
        "results": [c.as_source() for c in result.results],
    }


@server.tool(
    description=(
        "Fetch real German example sentences (with English translations where "
        "available) for a word from Tatoeba's community sentence database."
    )
)
async def german_examples(word: str, limit: int = 5) -> list[dict[str, Any]] | str:
    try:
        return await german_data.example_sentences(word, limit=limit)
    except Exception as exc:
        log.warning("mcp_german_examples_failed", word=word, error=str(exc))
        return f"Couldn't fetch example sentences for '{word}' right now."


if __name__ == "__main__":
    server.run()
