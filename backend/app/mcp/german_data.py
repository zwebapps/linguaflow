"""External, keyless German-language data sources: Wiktionary, Wikipedia, Tatoeba.

Deliberately DB-free (no `app.db` import) so `data_server.py` can run as a fully
standalone MCP server process with nothing but `httpx` and an optional Redis.

Why Wiktionary for noun gender: the LLM dictionary fallback in
`app.ai.tools.dictionary` is explicitly labelled `source="llm"` because a model can
hallucinate a noun's article with total confidence. Wiktionary's structured German
entries (`=== Substantiv, m ===`) are *authoritative* — sourced from a
community-maintained reference, not generated — so parsing them out is strictly
better than an LLM guess for exactly the fact (gender/plural) a wrong answer hurts
the learner most on.

Every public function here degrades gracefully: a network failure, a non-200, a
timeout, or unparseable JSON/text logs a warning and returns an empty result
(`{}`, `[]`, or `None`) — it never raises into a caller, because both the MCP tool
layer (server.py/data_server.py) and any future LangChain tool wrapping these must
stay up when Wikimedia or Tatoeba has a bad day.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from app.core.cache import get_client as get_redis_client

log = structlog.get_logger(__name__)

# Wikimedia requires a descriptive User-Agent identifying the app + a contact
# point (https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy). Tatoeba
# has no such formal policy but it costs nothing to be an equally polite citizen.
_USER_AGENT = (
    "LinguaFlowAI/1.0 (https://github.com/linguaflow/linguaflow-ai; "
    "contact: support@linguaflow.dev) httpx"
)
_TIMEOUT_SECONDS = 12.0

_WIKTIONARY_DE_API = "https://de.wiktionary.org/w/api.php"
_WIKIPEDIA_DE_API = "https://de.wikipedia.org/w/api.php"
_TATOEBA_SEARCH_API = "https://tatoeba.org/en/api_v0/search"

# Reference data is stable — a noun's gender doesn't change week to week — so a
# long TTL is appropriate and keeps us well clear of Wikimedia/Tatoeba rate limits.
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# German noun grammatical gender → definite article, the whole reason this module
# is worth having: `der`/`die`/`das` computed from a cited source, not guessed.
GENDER_TO_ARTICLE: dict[str, str] = {"m": "der", "f": "die", "n": "das"}


def _client(**headers: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT, **headers}
    )


# ── Cache (best-effort; a Redis outage never blocks a lookup) ──────────────────


async def _cache_get(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception as exc:  # cache is best-effort, never fatal
        log.warning("mcp_cache_read_failed", key=key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        log.warning("mcp_cache_corrupt_entry", key=key, error=str(exc))
        return None


async def _cache_set(key: str, value: Any, ttl: int = _CACHE_TTL_SECONDS) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        log.warning("mcp_cache_write_failed", key=key, error=str(exc))


# ── Wiktionary DE: authoritative word data ──────────────────────────────────────

# `=== Substantiv, m ===` / `=== Verb ===` / `=== Adjektiv ===` — the section
# header that carries part of speech and, for nouns, grammatical gender.
#
# The POS is matched against a KNOWN SET, not "any word in a === heading ===".
# A Wiktionary page has many such headings ("Übersetzungen", "Herkunft",
# "Redewendungen"), and a permissive pattern happily returned pos="Übersetzungen"
# for `gehen` — verified against live data.
_WORD_CLASSES = (
    "Substantiv", "Verb", "Adjektiv", "Adverb", "Pronomen", "Artikel",
    "Präposition", "Konjunktion", "Numerale", "Interjektion", "Partikel",
)
#
# The heading carries the word class first, then any number of comma-separated
# qualifiers: `=== Substantiv, m ===` but also
# `=== Verb, unregelmäßig, intransitiv ===` (live example: `gehen`). So capture the
# class and the whole tail, and pick the gender out of the tail separately — an
# earlier version required the gender to be the *only* qualifier and therefore
# found no POS at all for any verb carrying extra labels.
_POS_GENDER_RE = re.compile(
    r"===\s*(" + "|".join(_WORD_CLASSES) + r")\b([^=\n]*)===",
)

# `Worttrennung: Tisch, Plural: Ti·sche` — the plural follows a `Plural:` label.
#
# Constrained to a single word-like token on purpose. Wiktionary also writes prose
# such as "Plural: Der s-Plural ist umgangssprachlich", and a loose `[^\n,;]+`
# captured that whole sentence as the plural of `Mädchen` — also found live.
_PLURAL_RE = re.compile(r"Plural(?:\s*\d)?:\s*([A-Za-zÄÖÜäöüß·\-]+)\s*(?:[\n,;]|$)")

# `IPA: [tɪʃ]` — the phonemic transcription in square brackets.
_IPA_RE = re.compile(r"IPA:\s*\[([^\]]+)\]")

# Wiktionary marks syllable boundaries with U+00B7 ("Ti·sche"). That's a
# typographic aid for the dictionary, not part of the word — a learner shown
# "Ti·sche" would be learning a spelling that doesn't exist.
_SYLLABLE_DOT = "·"

# Words that are never a plural form — a sign the regex caught prose.
_PLURAL_STOPWORDS = {"der", "die", "das", "kein", "keine", "nur", "auch", "siehe"}


def _clean_plural(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.replace(_SYLLABLE_DOT, "").strip(" -,;")
    if not value or value.lower() in _PLURAL_STOPWORDS:
        return None
    return value


def parse_wiktionary_extract(extract: str) -> dict[str, Any]:
    """Pull part of speech, gender/article, plural, and IPA out of a Wiktionary
    plaintext extract. Pure and side-effect-free so it's independently testable
    against a fixture string — no HTTP involved.

    Returns an empty dict for empty/unparseable input rather than raising; any
    field it can't find is simply left out or set to ``None``.
    """
    if not extract or not extract.strip():
        return {}

    pos_match = _POS_GENDER_RE.search(extract)
    pos = pos_match.group(1) if pos_match else None
    # Gender is whichever comma-separated qualifier is exactly m, f or n —
    # matched as a whole token so "maskulin"/"intransitiv" can't be mistaken for it.
    gender = None
    if pos_match:
        for part in (pos_match.group(2) or "").split(","):
            token = part.strip().lower()
            if token in ("m", "f", "n"):
                gender = token
                break

    plural = _clean_plural(m.group(1) if (m := _PLURAL_RE.search(extract)) else None)

    ipa_match = _IPA_RE.search(extract)
    ipa = ipa_match.group(1).strip() if ipa_match else None

    return {
        "pos": pos,
        "gender": gender,
        "article": GENDER_TO_ARTICLE.get(gender) if gender else None,
        "plural": plural,
        "ipa": ipa,
    }


async def lookup_word(word: str) -> dict[str, Any]:
    """Fetch + parse a German word's Wiktionary entry. Empty dict on any failure
    or missing page (the word simply isn't in Wiktionary).
    """
    word = (word or "").strip()
    if not word:
        return {}

    cache_key = f"mcp:wiktionary:{word.lower()}"
    if (cached := await _cache_get(cache_key)) is not None:
        return cached

    try:
        async with _client() as client:
            resp = await client.get(
                _WIKTIONARY_DE_API,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": 1,
                    "format": "json",
                    "titles": word,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # httpx errors, non-2xx, malformed JSON — all the same to a caller
        log.warning("wiktionary_lookup_failed", word=word, error=str(exc))
        return {}

    pages = ((data.get("query") or {}).get("pages")) or {}
    extract = ""
    for page in pages.values():
        if not isinstance(page, dict) or "missing" in page:
            continue
        extract = page.get("extract") or ""
        if extract:
            break

    if not extract:
        return {}

    result = {"word": word, **parse_wiktionary_extract(extract)}
    await _cache_set(cache_key, result)
    return result


# ── Wikipedia DE: keyless full-text search + intro extracts ────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_search_markup(snippet: str) -> str:
    """Wikipedia search snippets carry `<span class="searchmatch">` highlighting."""
    return _HTML_TAG_RE.sub("", snippet or "").strip()


async def search_wikipedia(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Keyless full-text search over German Wikipedia. Empty list on failure."""
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, 20))

    cache_key = f"mcp:wikipedia:search:{query.lower()}:{limit}"
    if (cached := await _cache_get(cache_key)) is not None:
        return cached

    try:
        async with _client() as client:
            resp = await client.get(
                _WIKIPEDIA_DE_API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("wikipedia_search_failed", query=query, error=str(exc))
        return []

    hits = ((data.get("query") or {}).get("search")) or []
    results = [
        {"title": h.get("title"), "snippet": _strip_search_markup(h.get("snippet", ""))}
        for h in hits
        if isinstance(h, dict) and h.get("title")
    ]
    await _cache_set(cache_key, results)
    return results


async def get_wikipedia_extract(title: str) -> str | None:
    """Fetch the plaintext intro extract for a Wikipedia article. `None` on failure
    or a missing page.
    """
    title = (title or "").strip()
    if not title:
        return None

    cache_key = f"mcp:wikipedia:extract:{title.lower()}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached.get("extract")

    try:
        async with _client() as client:
            resp = await client.get(
                _WIKIPEDIA_DE_API,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "format": "json",
                    "titles": title,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("wikipedia_extract_failed", title=title, error=str(exc))
        return None

    pages = ((data.get("query") or {}).get("pages")) or {}
    extract: str | None = None
    for page in pages.values():
        if not isinstance(page, dict) or "missing" in page:
            continue
        extract = page.get("extract") or None
        break

    await _cache_set(cache_key, {"extract": extract})
    return extract


# ── Tatoeba: real example sentences ──────────────────────────────────────────────


def _english_translation(result: dict[str, Any]) -> str | None:
    """Tatoeba nests translations as groups of groups; find the first English one."""
    for group in result.get("translations") or []:
        if not isinstance(group, list):
            continue
        for translation in group:
            if isinstance(translation, dict) and translation.get("lang") == "eng":
                text = translation.get("text")
                if text:
                    return str(text)
    return None


async def example_sentences(word: str, limit: int = 5) -> list[dict[str, Any]]:
    """Real German example sentences from Tatoeba, with an English translation
    where one is available. Empty list on any failure.
    """
    word = (word or "").strip()
    if not word:
        return []
    limit = max(1, min(limit, 20))

    cache_key = f"mcp:tatoeba:{word.lower()}:{limit}"
    if (cached := await _cache_get(cache_key)) is not None:
        return cached

    try:
        async with _client() as client:
            resp = await client.get(
                _TATOEBA_SEARCH_API,
                params={"from": "deu", "query": word, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("tatoeba_search_failed", word=word, error=str(exc))
        return []

    hits = data.get("results") or []
    examples = [
        {"de": hit["text"], "en": _english_translation(hit)}
        for hit in hits[:limit]
        if isinstance(hit, dict) and hit.get("text")
    ]
    await _cache_set(cache_key, examples)
    return examples
