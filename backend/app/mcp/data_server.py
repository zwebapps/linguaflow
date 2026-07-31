"""The `german_data` functions, exposed as their own standalone MCP server.

This is deliberately a *separate* process from `server.py`: it has no DB
dependency at all (`german_data` never imports `app.db`), so it is the
dependency-free server `client.py` talks to out of the box — a real, runnable
MCP server that proves the client/adapter plumbing without needing Postgres,
Redis, or any app secrets configured.

Run standalone:

    python -m app.mcp.data_server

Client config (same shape as `server.py`)::

    {
      "mcpServers": {
        "linguaflow-german-data": {
          "command": "/absolute/path/to/backend/.venv/bin/python",
          "args": ["-m", "app.mcp.data_server"]
        }
      }
    }

This is also the default target of `app.mcp.client.load_mcp_tools()` — see that
module's `MCP_SERVERS` env var docs for how to point the client at a different
(including third-party) MCP server instead.
"""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.mcpserver import MCPServer

from app.mcp import german_data

log = structlog.get_logger(__name__)

server = MCPServer(
    "linguaflow-german-data",
    title="LinguaFlow German data sources",
    instructions=(
        "Keyless external German-language reference data: Wiktionary word entries, "
        "Wikipedia search/extracts, and Tatoeba example sentences. No database or "
        "app configuration required — this server only needs outbound HTTPS."
    ),
)


@server.tool(
    description=(
        "Look up a German word in Wiktionary: part of speech, grammatical gender "
        "(as der/die/das), plural, and IPA pronunciation."
    )
)
async def lookup_wiktionary(word: str) -> dict[str, Any] | str:
    try:
        result = await german_data.lookup_word(word)
    except Exception as exc:
        log.warning("mcp_data_lookup_wiktionary_failed", word=word, error=str(exc))
        return f"Couldn't look up '{word}' right now."
    if not result:
        return f"No Wiktionary entry found for '{word}'."
    return result


@server.tool(
    description="Keyless full-text search over German Wikipedia. Returns titles and snippets."
)
async def search_wikipedia(query: str, limit: int = 5) -> list[dict[str, Any]] | str:
    try:
        return await german_data.search_wikipedia(query, limit=limit)
    except Exception as exc:
        log.warning("mcp_data_search_wikipedia_failed", query=query, error=str(exc))
        return f"Wikipedia search for '{query}' failed."


@server.tool(
    description="Fetch the plaintext intro extract for a German Wikipedia article by title."
)
async def wikipedia_summary(title: str) -> str:
    try:
        extract = await german_data.get_wikipedia_extract(title)
    except Exception as exc:
        log.warning("mcp_data_wikipedia_summary_failed", title=title, error=str(exc))
        return f"Couldn't fetch a summary for '{title}' right now."
    return extract or f"No Wikipedia article found for '{title}'."


@server.tool(
    description=(
        "Fetch real German example sentences (with English translations where "
        "available) for a word from Tatoeba."
    )
)
async def german_examples(word: str, limit: int = 5) -> list[dict[str, Any]] | str:
    try:
        return await german_data.example_sentences(word, limit=limit)
    except Exception as exc:
        log.warning("mcp_data_german_examples_failed", word=word, error=str(exc))
        return f"Couldn't fetch example sentences for '{word}' right now."


if __name__ == "__main__":
    server.run()
