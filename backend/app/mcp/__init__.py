"""Model Context Protocol integration for LinguaFlow AI.

Two directions, four modules:

- ``server.py``      — exposes OUR domain tools (conjugation, dictionary, RAG search,
                        example sentences) as an MCP server over stdio, so any MCP
                        client (Claude Desktop, an IDE, another agent) can call them.
- ``german_data.py``  — DB-free external German-language data sources (Wiktionary,
                         Wikipedia, Tatoeba), used by both server.py and data_server.py.
- ``data_server.py``  — the ``german_data`` functions exposed as their OWN standalone
                         MCP server process, independent of the main app.
- ``client.py``       — an MCP CLIENT: connects to configured MCP servers (ours or
                         anyone else's) and adapts their tools into LangChain tools.

Nothing in this package is imported by ``app.main`` — each server is a standalone
entrypoint run with ``python -m app.mcp.server`` / ``python -m app.mcp.data_server``.
"""

from __future__ import annotations
