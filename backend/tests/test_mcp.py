"""Tests for the MCP integration (app/mcp/*).

Hermetic — HTTP to Wiktionary/Wikipedia/Tatoeba is faked with `respx`; Redis is
disabled via a monkeypatched `get_redis_client` so no test depends on a running
cache. The only real subprocess spawned is `app.mcp.data_server` itself, and only
to round-trip `list_tools()` — which never makes an outbound HTTP call — so that
test stays both fast and network-free.
"""

from __future__ import annotations

import sys

import httpx
import mcp_types as types
import pytest
import respx
from pydantic import ValidationError

from app.mcp import client as mcp_client
from app.mcp import german_data
from app.mcp.client import MCPServerConfig, load_mcp_tools, load_server_configs

WIKTIONARY_URL = "https://de.wiktionary.org/w/api.php"
WIKIPEDIA_URL = "https://de.wikipedia.org/w/api.php"
TATOEBA_URL = "https://tatoeba.org/en/api_v0/search"

# A realistic Wiktionary DE plaintext extract for "Tisch", trimmed to the parts
# the parser cares about — real extracts have far more sections, but this
# reproduces the exact shapes named in the task: `=== Substantiv, m ===`,
# `Plural: Ti·sche`, `IPA: [tɪʃ]`.
TISCH_EXTRACT = """Tisch (Deutsch)

=== Substantiv, m ===

Worttrennung:
Tisch, Plural: Ti·sche

Aussprache:
IPA: [tɪʃ]

Bedeutungen:
[1] ein Möbelstück mit einer ebenen Platte
"""


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch):
    """Every german_data function checks the cache first — force a miss/no-op
    everywhere so tests never depend on (or wait on) a real Redis connection.
    """
    monkeypatch.setattr(german_data, "get_redis_client", lambda: None)


# ── Wiktionary extract parser (pure function, no HTTP) ──────────────────────────


def test_parse_wiktionary_extract_tisch():
    parsed = german_data.parse_wiktionary_extract(TISCH_EXTRACT)
    assert parsed["pos"] == "Substantiv"
    assert parsed["gender"] == "m"
    assert parsed["article"] == "der"
    # Syllable dots are stripped — "Ti·sche" is a hyphenation aid, not spelling.
    assert parsed["plural"] == "Tische"
    assert parsed["ipa"] == "tɪʃ"


def test_parse_wiktionary_extract_empty_input():
    assert german_data.parse_wiktionary_extract("") == {}
    assert german_data.parse_wiktionary_extract("   ") == {}


def test_parse_wiktionary_extract_no_recognisable_sections():
    assert german_data.parse_wiktionary_extract("just some prose, nothing structured") == {
        "pos": None,
        "gender": None,
        "article": None,
        "plural": None,
        "ipa": None,
    }


@pytest.mark.parametrize(
    "gender,article",
    [("m", "der"), ("f", "die"), ("n", "das")],
)
def test_gender_to_article_mapping(gender, article):
    assert german_data.GENDER_TO_ARTICLE[gender] == article


# ── lookup_word (Wiktionary) ─────────────────────────────────────────────────────


@respx.mock
async def test_lookup_word_success():
    respx.get(WIKTIONARY_URL).mock(
        return_value=httpx.Response(
            200,
            json={"query": {"pages": {"123": {"title": "Tisch", "extract": TISCH_EXTRACT}}}},
        )
    )
    result = await german_data.lookup_word("Tisch")
    assert result["word"] == "Tisch"
    assert result["article"] == "der"
    assert result["plural"] == "Tische"  # syllable dot stripped
    assert result["ipa"] == "tɪʃ"


@respx.mock
async def test_lookup_word_missing_page_returns_empty():
    respx.get(WIKTIONARY_URL).mock(
        return_value=httpx.Response(
            200, json={"query": {"pages": {"-1": {"title": "Xyzzy", "missing": ""}}}}
        )
    )
    assert await german_data.lookup_word("Xyzzy") == {}


@respx.mock
async def test_lookup_word_http_500_degrades_to_empty():
    respx.get(WIKTIONARY_URL).mock(return_value=httpx.Response(500, text="upstream boom"))
    assert await german_data.lookup_word("Tisch") == {}


@respx.mock
async def test_lookup_word_timeout_degrades_to_empty():
    respx.get(WIKTIONARY_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    assert await german_data.lookup_word("Tisch") == {}


@respx.mock
async def test_lookup_word_malformed_json_degrades_to_empty():
    respx.get(WIKTIONARY_URL).mock(return_value=httpx.Response(200, text="not json{"))
    assert await german_data.lookup_word("Tisch") == {}


async def test_lookup_word_blank_input_short_circuits():
    # No respx mock registered at all — a network call here would fail the test.
    assert await german_data.lookup_word("   ") == {}


# ── search_wikipedia / get_wikipedia_extract ────────────────────────────────────


@respx.mock
async def test_search_wikipedia_success_strips_highlight_markup():
    respx.get(WIKIPEDIA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Berlin",
                            "snippet": (
                                '<span class="searchmatch">Berlin</span> ist die Hauptstadt'
                            ),
                        }
                    ]
                }
            },
        )
    )
    results = await german_data.search_wikipedia("Berlin", limit=3)
    assert results == [{"title": "Berlin", "snippet": "Berlin ist die Hauptstadt"}]


@respx.mock
async def test_search_wikipedia_degrades_on_error():
    respx.get(WIKIPEDIA_URL).mock(return_value=httpx.Response(503, text="nope"))
    assert await german_data.search_wikipedia("Berlin") == []


@respx.mock
async def test_get_wikipedia_extract_success():
    respx.get(WIKIPEDIA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "pages": {"1": {"title": "Berlin", "extract": "Berlin ist die Hauptstadt."}}
                }
            },
        )
    )
    assert await german_data.get_wikipedia_extract("Berlin") == "Berlin ist die Hauptstadt."


@respx.mock
async def test_get_wikipedia_extract_missing_page_returns_none():
    respx.get(WIKIPEDIA_URL).mock(
        return_value=httpx.Response(
            200, json={"query": {"pages": {"-1": {"title": "Nope", "missing": ""}}}}
        )
    )
    assert await german_data.get_wikipedia_extract("Nope") is None


# ── example_sentences (Tatoeba) ──────────────────────────────────────────────────


@respx.mock
async def test_example_sentences_success_with_translation():
    respx.get(TATOEBA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "text": "Der Tisch ist neu.",
                        "translations": [[{"lang": "eng", "text": "The table is new."}]],
                    }
                ]
            },
        )
    )
    examples = await german_data.example_sentences("Tisch", limit=5)
    assert examples == [{"de": "Der Tisch ist neu.", "en": "The table is new."}]


@respx.mock
async def test_example_sentences_no_translation_available():
    respx.get(TATOEBA_URL).mock(
        return_value=httpx.Response(
            200, json={"results": [{"text": "Der Tisch ist neu.", "translations": []}]}
        )
    )
    examples = await german_data.example_sentences("Tisch")
    assert examples == [{"de": "Der Tisch ist neu.", "en": None}]


@respx.mock
async def test_example_sentences_degrades_on_malformed_json():
    respx.get(TATOEBA_URL).mock(return_value=httpx.Response(200, text="{not valid"))
    assert await german_data.example_sentences("Tisch") == []


# ── Our MCP server (server.py) ───────────────────────────────────────────────────


async def test_conjugate_verb_gehen_praeteritum():
    from app.mcp.server import conjugate_verb

    result = await conjugate_verb("gehen", "praeteritum")
    assert isinstance(result, dict)
    assert result["forms"]["ich"] == "ging"
    assert result["forms"]["wir"] == "gingen"


async def test_conjugate_verb_bad_infinitive_returns_error_string():
    from app.mcp.server import conjugate_verb

    result = await conjugate_verb("xyz", "praesens")
    assert isinstance(result, str)
    assert "xyz" in result


async def test_conjugate_verb_via_mcp_protocol_in_process():
    """Round-trips through the real MCP call_tool path (schema validation +
    content serialization), not just the bare Python function — proves the
    server wiring, not only the conjugation engine underneath it.
    """
    from mcp.client.client import Client

    from app.mcp.server import server as domain_server

    async with Client(domain_server) as client:
        result = await client.call_tool("conjugate_verb", {"verb": "gehen", "tense": "praeteritum"})
    assert not result.is_error
    text = "\n".join(b.text for b in result.content if isinstance(b, types.TextContent))
    assert "ging" in text
    assert "gingen" in text


async def test_lookup_german_word_tool_uses_german_data(monkeypatch: pytest.MonkeyPatch):
    import app.mcp.server as server_mod

    async def _fake_lookup(lemma: str):
        assert lemma == "Tisch"
        return {
            "word": "Tisch",
            "article": "der",
            "plural": "Ti·sche",
            "ipa": "tɪʃ",
            "gender": "m",
            "pos": "Substantiv",
        }

    monkeypatch.setattr(server_mod.german_data, "lookup_word", _fake_lookup)
    result = await server_mod.lookup_german_word("Tisch")
    assert result["article"] == "der"


async def test_lookup_german_word_tool_reports_no_entry(monkeypatch: pytest.MonkeyPatch):
    import app.mcp.server as server_mod

    async def _fake_lookup(lemma: str):
        return {}

    monkeypatch.setattr(server_mod.german_data, "lookup_word", _fake_lookup)
    result = await server_mod.lookup_german_word("Xyzzy")
    assert isinstance(result, str)
    assert "Xyzzy" in result


async def test_lookup_german_word_tool_never_raises_on_backend_error(
    monkeypatch: pytest.MonkeyPatch,
):
    import app.mcp.server as server_mod

    async def _boom(lemma: str):
        raise RuntimeError("wiktionary is down")

    monkeypatch.setattr(server_mod.german_data, "lookup_word", _boom)
    result = await server_mod.lookup_german_word("Tisch")
    assert isinstance(result, str)


async def test_german_examples_tool(monkeypatch: pytest.MonkeyPatch):
    import app.mcp.server as server_mod

    async def _fake_examples(word: str, limit: int = 5):
        return [{"de": "Der Tisch ist neu.", "en": "The table is new."}]

    monkeypatch.setattr(server_mod.german_data, "example_sentences", _fake_examples)
    result = await server_mod.german_examples("Tisch")
    assert result == [{"de": "Der Tisch ist neu.", "en": "The table is new."}]


async def test_search_knowledge_base_tool_opens_and_closes_a_session(
    monkeypatch: pytest.MonkeyPatch,
):
    import app.mcp.server as server_mod
    from app.rag.contracts import RetrievedChunk, SearchResult

    entered: list[str] = []

    class _FakeSessionCM:
        async def __aenter__(self):
            entered.append("open")
            return "fake-db-session"

        async def __aexit__(self, *exc_info):
            entered.append("close")
            return False

    def _fake_session_local():
        return _FakeSessionCM()

    async def _fake_retrieve(db, query, *, cefr_level=None, k=None, **kwargs):
        assert db == "fake-db-session"
        return SearchResult(
            query=query,
            strategy="hybrid",
            results=[
                RetrievedChunk(
                    id="c1",
                    document_id="d1",
                    title="Grammar notes",
                    text="Full text",
                    snippet="Full te...",
                    score=0.9,
                )
            ],
        )

    monkeypatch.setattr(server_mod, "SessionLocal", _fake_session_local)
    monkeypatch.setattr(server_mod.rag_retriever, "retrieve", _fake_retrieve)

    result = await server_mod.search_knowledge_base("Akkusativ", cefr_level="A2")
    assert result["query"] == "Akkusativ"
    assert result["results"][0]["title"] == "Grammar notes"
    assert entered == ["open", "close"]


async def test_search_knowledge_base_tool_degrades_on_failure(monkeypatch: pytest.MonkeyPatch):
    import app.mcp.server as server_mod

    class _FakeSessionCM:
        async def __aenter__(self):
            return "fake-db-session"

        async def __aexit__(self, *exc_info):
            return False

    async def _boom(db, query, **kwargs):
        raise RuntimeError("vector store is down")

    monkeypatch.setattr(server_mod, "SessionLocal", lambda: _FakeSessionCM())
    monkeypatch.setattr(server_mod.rag_retriever, "retrieve", _boom)

    result = await server_mod.search_knowledge_base("Akkusativ")
    assert isinstance(result, str)


# ── data_server.py tools (thin wrappers over german_data) ──────────────────────


async def test_data_server_lookup_wiktionary_tool(monkeypatch: pytest.MonkeyPatch):
    import app.mcp.data_server as data_server_mod

    async def _fake_lookup(word: str):
        return {"word": "Hund", "article": "der"}

    monkeypatch.setattr(data_server_mod.german_data, "lookup_word", _fake_lookup)
    result = await data_server_mod.lookup_wiktionary("Hund")
    assert result["article"] == "der"


# ── client.py: JSON schema → pydantic model ──────────────────────────────────────


def test_schema_to_pydantic_model_required_and_optional_fields():
    schema = {
        "type": "object",
        "properties": {
            "word": {"type": "string", "description": "the word"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["word"],
    }
    model = mcp_client._schema_to_pydantic_model("german_examples", schema)
    instance = model(word="Tisch")
    assert instance.word == "Tisch"
    assert instance.limit == 5

    with pytest.raises(ValidationError):
        model()  # 'word' is required


def test_schema_to_pydantic_model_rejects_non_object_schema():
    with pytest.raises(ValueError, match="not a JSON object schema"):
        mcp_client._schema_to_pydantic_model("bad_tool", {"type": "string"})


def test_schema_to_pydantic_model_rejects_unsupported_property_type():
    schema = {"type": "object", "properties": {"x": {"type": "frobnicate"}}}
    with pytest.raises(ValueError, match="unsupported type"):
        mcp_client._schema_to_pydantic_model("bad_tool", schema)


def test_make_langchain_tool_skips_malformed_schema():
    tool = types.Tool(
        name="bad_tool",
        description="d",
        inputSchema={"type": "object", "properties": {"x": {"type": "frobnicate"}}},
    )
    config = MCPServerConfig(name="server", command=sys.executable)
    result = mcp_client._make_langchain_tool(config, tool, 5.0)
    assert result is None


def test_make_langchain_tool_wraps_valid_schema():
    tool = types.Tool(
        name="german_examples",
        description="fetch examples",
        inputSchema={
            "type": "object",
            "properties": {"word": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
            "required": ["word"],
        },
    )
    config = MCPServerConfig(name="data", command=sys.executable)
    result = mcp_client._make_langchain_tool(config, tool, 5.0)
    assert result is not None
    assert result.name == "mcp__data__german_examples"


# ── client.py: config loading from MCP_SERVERS ───────────────────────────────────


def test_load_server_configs_defaults_to_our_own_data_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MCP_SERVERS", raising=False)
    configs = load_server_configs()
    assert len(configs) == 1
    assert configs[0].name == "linguaflow-german-data"
    assert configs[0].args == ["-m", "app.mcp.data_server"]


def test_load_server_configs_parses_valid_json():
    raw = (
        '[{"name": "web-search", "command": "npx", '
        '"args": ["-y", "@some-org/mcp-web-search"], "env": {"API_KEY": "x"}}]'
    )
    configs = load_server_configs(raw)
    assert configs == [
        MCPServerConfig(
            name="web-search",
            command="npx",
            args=["-y", "@some-org/mcp-web-search"],
            env={"API_KEY": "x"},
        )
    ]


def test_load_server_configs_falls_back_on_invalid_json():
    configs = load_server_configs("not json at all {{{")
    assert configs[0].name == "linguaflow-german-data"


def test_load_server_configs_skips_malformed_entries_but_keeps_valid_ones():
    raw = '[{"name": "ok", "command": "npx"}, {"command": "missing-name"}]'
    configs = load_server_configs(raw)
    assert len(configs) == 1
    assert configs[0].name == "ok"


# ── client.py: connecting to a real (unreachable / real) server process ─────────


async def test_load_mcp_tools_skips_unreachable_server():
    configs = [MCPServerConfig(name="ghost", command="/nonexistent/binary-xyz", args=[])]
    tools = await load_mcp_tools(configs, connect_timeout=3.0)
    assert tools == []


async def test_mcp_tool_health_reports_unreachable_server():
    from app.mcp.client import mcp_tool_health

    configs = [MCPServerConfig(name="ghost", command="/nonexistent/binary-xyz", args=[])]
    report = await mcp_tool_health(configs, connect_timeout=3.0)
    assert report["ghost"]["reachable"] is False
    assert report["ghost"]["tool_count"] == 0
    assert report["ghost"]["error"]


async def test_data_server_round_trip_list_tools_and_health():
    """Spawns `app.mcp.data_server` for real and lists its tools over stdio.

    No HTTP call happens anywhere in this test — `list_tools()` only reflects
    registered tool metadata, so this proves the client/subprocess/schema-adapter
    wiring end-to-end without touching the network.
    """
    configs = [
        MCPServerConfig(name="data", command=sys.executable, args=["-m", "app.mcp.data_server"])
    ]
    tools = await load_mcp_tools(configs, connect_timeout=10.0)
    names = {t.name for t in tools}
    assert names == {
        "mcp__data__lookup_wiktionary",
        "mcp__data__search_wikipedia",
        "mcp__data__wikipedia_summary",
        "mcp__data__german_examples",
    }

    from app.mcp.client import mcp_tool_health

    report = await mcp_tool_health(configs, connect_timeout=10.0)
    assert report["data"]["reachable"] is True
    assert report["data"]["tool_count"] == 4


# ── Wiktionary parser: regressions found against LIVE data ────────────────────
#
# Fixture tests passed while all three of these were broken in production. The
# shapes below are copied from real de.wiktionary.org extracts.


def test_pos_is_found_when_the_heading_carries_extra_qualifiers() -> None:
    """`gehen` is `=== Verb, unregelmäßig, intransitiv ===`.

    Requiring the gender to be the only qualifier returned pos=None for every
    verb labelled irregular/transitive — i.e. most of them.
    """
    from app.mcp.german_data import parse_wiktionary_extract

    got = parse_wiktionary_extract(
        "== gehen (Deutsch) ==\n=== Verb, unregelmäßig, intransitiv ===\n"
        "Aussprache:\nIPA: [ˈɡeːən]\n=== Übersetzungen ===\n"
    )
    assert got["pos"] == "Verb"
    assert got["gender"] is None
    assert got["ipa"] == "ˈɡeːən"


def test_a_section_heading_is_not_mistaken_for_a_part_of_speech() -> None:
    """Matching any word in a `=== … ===` heading yielded pos="Übersetzungen"."""
    from app.mcp.german_data import parse_wiktionary_extract

    got = parse_wiktionary_extract("=== Herkunft ===\ntext\n=== Übersetzungen ===\nmore\n")
    assert got["pos"] is None


def test_syllable_dots_are_stripped_from_the_plural() -> None:
    """Wiktionary writes "Ti·sche"; U+00B7 is a hyphenation aid, not spelling.

    Showing a learner "Ti·sche" teaches a word that doesn't exist.
    """
    from app.mcp.german_data import parse_wiktionary_extract

    got = parse_wiktionary_extract(
        "=== Substantiv, m ===\nWorttrennung: Tisch, Plural: Ti·sche\nIPA: [tɪʃ]\n"
    )
    assert got["plural"] == "Tische"
    assert got["article"] == "der"


def test_prose_after_a_plural_label_is_rejected() -> None:
    """`Mädchen` has "Plural: Der s-Plural ist umgangssprachlich…" — that captured
    a whole sentence as the plural."""
    from app.mcp.german_data import parse_wiktionary_extract

    got = parse_wiktionary_extract(
        "=== Substantiv, n ===\nPlural: Der s-Plural ist umgangssprachlich\nIPA: [ˈmɛːtçən]\n"
    )
    assert got["plural"] is None, "prose must not be reported as a plural form"
    assert got["article"] == "das"


def test_a_qualifier_beginning_with_m_is_not_read_as_a_gender() -> None:
    """"maskulin" starts with m; only a standalone m/f/n token is a gender."""
    from app.mcp.german_data import parse_wiktionary_extract

    got = parse_wiktionary_extract("=== Verb, medial, intransitiv ===\nIPA: [x]\n")
    assert got["gender"] is None
    assert got["article"] is None


def test_all_three_genders_map_to_the_right_article() -> None:
    from app.mcp.german_data import parse_wiktionary_extract

    for gender, article in (("m", "der"), ("f", "die"), ("n", "das")):
        got = parse_wiktionary_extract(f"=== Substantiv, {gender} ===\nPlural: Dinge\n")
        assert got["article"] == article
