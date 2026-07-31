"""MCP CLIENT: connect to configured MCP servers, adapt their tools into LangChain
tools the tutor agent could use.

Robustness is the whole point of this module — a misbehaving MCP server (fails to
start, hangs, advertises a broken schema) must never take the app down or even
block startup. Every failure mode here is caught and logged; the caller gets back
whatever subset of tools loaded cleanly, possibly an empty list.

Transport: stdio only (spawns the server as a subprocess and speaks newline-
delimited JSON-RPC over its stdin/stdout — see `mcp.client.stdio.stdio_client`).
Built on `mcp.client.client.Client`, the SDK's high-level client (v2 API — this
replaces the old pattern of driving `ClientSession` directly; verified against
`.venv/lib/python3.11/site-packages/mcp/client/client.py`, which accepts a
`Transport` instance — exactly what `stdio_client(params)` returns — and handles
the initialize handshake internally).

Configuration — the `MCP_SERVERS` env var (JSON array), e.g.::

    MCP_SERVERS='[{"name": "web-search", "command": "npx",
                   "args": ["-y", "@some-org/mcp-web-search"],
                   "env": {"API_KEY": "..."}}]'

With `MCP_SERVERS` unset (the default), the client points at our own
`app.mcp.data_server` — zero setup required, no external process to install.
Pointing this at any public MCP server (Claude Desktop's registry, an internal
tool server, a vendor's server) is *purely* a config change: add an entry to the
JSON array, no code here changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import mcp_types as types
import structlog
from langchain_core.tools import BaseTool, StructuredTool
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import BaseModel, Field, create_model

log = structlog.get_logger(__name__)

# Generous but bounded: a subprocess that hasn't answered `initialize`/`list_tools`
# (or a tool call that hasn't returned) by this point is treated as unreachable/
# hung rather than left to block the caller indefinitely.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0

_MCP_SERVERS_ENV_VAR = "MCP_SERVERS"


# ── Configuration ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class MCPServerConfig:
    """One stdio MCP server to connect to: how to spawn it."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None


def _default_configs() -> list[MCPServerConfig]:
    """Our own data server — dependency-free, works with zero setup."""
    return [
        MCPServerConfig(
            name="linguaflow-german-data",
            command=sys.executable,
            args=["-m", "app.mcp.data_server"],
        )
    ]


def load_server_configs(raw: str | None = None) -> list[MCPServerConfig]:
    """Parse `MCP_SERVERS` (JSON array of `{name, command, args?, env?}`) into
    configs. Missing/empty/unparseable env var falls back to our own data server
    so the client works out of the box; a malformed *individual* entry is skipped
    (with a warning) rather than discarding the whole list.
    """
    raw = raw if raw is not None else os.environ.get(_MCP_SERVERS_ENV_VAR)
    if not raw or not raw.strip():
        return _default_configs()

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        log.warning("mcp_servers_env_invalid_json", error=str(exc))
        return _default_configs()

    if not isinstance(parsed, list):
        log.warning("mcp_servers_env_not_a_list", value_type=type(parsed).__name__)
        return _default_configs()

    configs: list[MCPServerConfig] = []
    for item in parsed:
        try:
            if not isinstance(item, dict):
                raise TypeError(f"expected an object, got {type(item).__name__}")
            configs.append(
                MCPServerConfig(
                    name=str(item["name"]),
                    command=str(item["command"]),
                    args=[str(a) for a in item.get("args", [])],
                    env={str(k): str(v) for k, v in (item.get("env") or {}).items()} or None,
                )
            )
        except Exception as exc:
            log.warning("mcp_server_config_invalid", entry=item, error=str(exc))

    return configs or _default_configs()


# ── JSON schema → pydantic model (for LangChain's `args_schema`) ────────────────

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_]")


def _pascal_case(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("_") or "Tool"
    return "".join(part.capitalize() or "_" for part in cleaned.split("_"))


def _schema_to_pydantic_model(tool_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Best-effort JSON-schema → pydantic model for an MCP tool's `inputSchema`.

    Deliberately narrow: MCP tool schemas are simple JSON Schema objects (not full
    JSON Schema — no $ref, oneOf, allOf here), so a straightforward property-by-
    property mapping covers the realistic case. Anything that doesn't fit (missing
    `type: object`, no `properties`, an unsupported property type) raises
    `ValueError`, which the caller treats as "skip this tool, log a warning" —
    never a reason to fail the whole server's tool list.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError(f"tool {tool_name!r}: input schema is not a JSON object schema")

    properties = schema.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise ValueError(f"tool {tool_name!r}: 'properties' is not an object")

    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            raise ValueError(f"tool {tool_name!r}: property {prop_name!r} is malformed")

        json_type = prop_schema.get("type", "string")
        py_type = _JSON_TYPE_MAP.get(json_type)
        if py_type is None:
            raise ValueError(
                f"tool {tool_name!r}: property {prop_name!r} has unsupported type {json_type!r}"
            )

        description = prop_schema.get("description")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=description))
        else:
            default = prop_schema.get("default")
            fields[prop_name] = (py_type | None, Field(default, description=description))

    model_name = f"{_pascal_case(tool_name)}Args"
    return create_model(model_name, **fields)  # type: ignore[call-overload, no-any-return]


# ── Connecting + calling ─────────────────────────────────────────────────────────


def _params_for(config: MCPServerConfig) -> StdioServerParameters:
    return StdioServerParameters(command=config.command, args=config.args, env=config.env)


async def _list_remote_tools(
    config: MCPServerConfig, timeout_seconds: float
) -> list[types.Tool]:
    """Connect, complete the MCP handshake, list tools, disconnect. Raises on any
    failure — the caller is responsible for catching and skipping.
    """
    async with asyncio.timeout(timeout_seconds):
        async with Client(stdio_client(_params_for(config))) as client:
            listing = await client.list_tools()
    return list(listing.tools)


async def _call_remote_tool(
    config: MCPServerConfig, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
) -> str:
    """Open a fresh connection for one tool call and close it again.

    Short-lived-per-call rather than one long-lived session per server: a stdio
    MCP server is a subprocess, and a subprocess that dies or hangs mid-session
    would otherwise poison every subsequent call through it. Reconnecting is more
    expensive but means one bad call can never take out the tool for good.
    """
    async with asyncio.timeout(timeout_seconds):
        async with Client(stdio_client(_params_for(config))) as client:
            result = await client.call_tool(tool_name, arguments)

    text = "\n".join(
        block.text for block in result.content if isinstance(block, types.TextContent)
    )
    if result.is_error:
        return f"MCP tool '{tool_name}' returned an error: {text or 'no details'}"
    return text or "(tool returned no content)"


def _make_langchain_tool(
    config: MCPServerConfig, tool: types.Tool, timeout_seconds: float
) -> BaseTool | None:
    """Adapt one MCP tool into a LangChain `StructuredTool`, or `None` if its
    schema can't be represented (logged, not raised — the caller skips it).
    """
    try:
        args_model = _schema_to_pydantic_model(tool.name, tool.input_schema)
    except Exception as exc:
        log.warning(
            "mcp_tool_schema_skipped", server=config.name, tool=tool.name, error=str(exc)
        )
        return None

    async def _invoke(**kwargs: Any) -> str:
        try:
            return await _call_remote_tool(config, tool.name, kwargs, timeout_seconds)
        except TimeoutError:
            log.warning("mcp_tool_call_timed_out", server=config.name, tool=tool.name)
            return f"MCP tool '{tool.name}' on server '{config.name}' timed out."
        except Exception as exc:
            log.warning(
                "mcp_tool_call_failed", server=config.name, tool=tool.name, error=str(exc)
            )
            return f"MCP tool '{tool.name}' on server '{config.name}' failed: {exc}"

    # Namespaced by server so two servers can't advertise colliding tool names.
    qualified_name = f"mcp__{config.name}__{tool.name}"
    try:
        return StructuredTool.from_function(
            coroutine=_invoke,
            name=qualified_name,
            description=tool.description or f"MCP tool '{tool.name}' from '{config.name}'.",
            args_schema=args_model,
        )
    except Exception as exc:
        # Belt-and-suspenders: a valid-looking schema that pydantic/LangChain still
        # rejects (e.g. a reserved field name) shouldn't be fatal either.
        log.warning(
            "mcp_tool_wrap_failed", server=config.name, tool=tool.name, error=str(exc)
        )
        return None


# ── Public API ────────────────────────────────────────────────────────────────────


async def load_mcp_tools(
    configs: Sequence[MCPServerConfig] | None = None,
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> list[BaseTool]:
    """Connect to every configured MCP server, list its tools, and return the
    union as LangChain tools. `configs` defaults to `load_server_configs()`
    (the `MCP_SERVERS` env var, or our own data server).

    A server that fails to start, times out, or is otherwise unreachable is
    skipped with a warning — this never raises.
    """
    resolved = list(configs) if configs is not None else load_server_configs()
    tools: list[BaseTool] = []

    for config in resolved:
        try:
            remote_tools = await _list_remote_tools(config, connect_timeout)
        except TimeoutError:
            log.warning("mcp_server_connect_timed_out", server=config.name)
            continue
        except Exception as exc:
            log.warning("mcp_server_unreachable", server=config.name, error=str(exc))
            continue

        for tool in remote_tools:
            lc_tool = _make_langchain_tool(config, tool, connect_timeout)
            if lc_tool is not None:
                tools.append(lc_tool)

    return tools


async def mcp_tool_health(
    configs: Sequence[MCPServerConfig] | None = None,
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Per-server reachability + tool count, for an admin/health surface.

    Shape: ``{server_name: {"reachable": bool, "tool_count": int, "error": str | None}}``.
    Never raises — every server is probed independently and a failure on one is
    just an entry with `reachable: False`, not a raised exception.
    """
    resolved = list(configs) if configs is not None else load_server_configs()
    report: dict[str, dict[str, Any]] = {}

    for config in resolved:
        entry: dict[str, Any] = {"reachable": False, "tool_count": 0, "error": None}
        try:
            remote_tools = await _list_remote_tools(config, connect_timeout)
            entry["reachable"] = True
            entry["tool_count"] = len(remote_tools)
        except TimeoutError:
            entry["error"] = "connect timed out"
            log.warning("mcp_health_check_timed_out", server=config.name)
        except Exception as exc:
            entry["error"] = str(exc)[:300]
            log.warning("mcp_health_check_failed", server=config.name, error=str(exc))
        report[config.name] = entry

    return report
