# DeutschFlow AI — Architecture (as built)

This documents the system **as implemented and verified** — every flow below was
exercised against the live stack. Read this to understand, modify, or extend the
project. The frontend↔backend wire contract lives in [API_CONTRACT.md](API_CONTRACT.md);
this file explains what happens behind it and why.

> The original pre-build specification (which planned Supabase/Vercel/Render) is
> preserved at [docs/INITIAL_SPEC.md](docs/INITIAL_SPEC.md). The build kept its ideas —
> AI Router, RAG seams, admin-only ingestion — but runs self-hosted: FastAPI + Postgres +
> Qdrant + Redis via docker-compose, Next.js frontend. Production deployment remains an
> env-var swap by design (§10).

---

## Contents

1. [System overview](#1-system-overview)
2. [The AI Router — multi-model switching](#2-the-ai-router)
3. [Flow: a tutor chat turn (SSE)](#3-flow-a-tutor-chat-turn)
4. [Flow: RAG — ingestion and retrieval](#4-flow-rag)
5. [Flow: speaking practice (voice)](#5-flow-speaking-practice)
6. [Native language ↔ target language](#6-native-language--target-language)
7. [Tool calling](#7-tool-calling)
8. [A/B testing of retrieval strategies](#8-ab-testing)
9. [MCP — servers and client](#9-mcp)
10. [Data model & migrations](#10-data-model--migrations)
11. [Security model](#11-security-model)
12. [Observability, cost & limits](#12-observability-cost--limits)
13. [Evaluation harness](#13-evaluation-harness)
14. [How to extend](#14-how-to-extend)
15. [Decision log](#15-decision-log)

---

## 1. System overview

```
                    ┌────────────────────────────┐
                    │   Browser (learner/admin)   │
                    │  Next.js UI · MediaRecorder │
                    │  SpeechSynthesis (de-DE TTS)│
                    └──────────┬─────────────────┘
                               │ REST + SSE (Bearer JWT) — API_CONTRACT.md
                    ┌──────────▼─────────────────┐
                    │    FastAPI  (:8000)         │
                    │  ┌───────────────────────┐  │
                    │  │ api/v1  (13 routers)  │  │   auth · chat · tools · library
                    │  └───────────┬───────────┘  │   vocab · flashcards · quiz
                    │  ┌───────────▼───────────┐  │   writing · analysis · speaking
                    │  │ AI Router (app/ai)    │──┼─────────► OpenRouter
                    │  │ task→model, fallbacks │  │   chat/completions · embeddings
                    │  │ cache · usage · cost  │  │   audio/transcriptions
                    │  └───────────┬───────────┘  │
                    │  ┌───────────▼───────────┐  │
                    │  │ LangChain agent       │  │   create_agent + 6 tools
                    │  │ RAG retriever (hybrid)│  │
                    │  └───────────────────────┘  │
                    │  workers: ingest · scheduler│
                    │  mcp: server · data_server  │
                    └───┬──────────┬─────────┬────┘
                        │          │         │
                 ┌──────▼───┐ ┌────▼────┐ ┌──▼──────┐
                 │ Postgres │ │ Qdrant  │ │  Redis  │
                 │  :5442   │ │  :6333  │ │  :6390  │
                 │ 18 tables│ │ vectors │ │ cache · │
                 │ Alembic  │ │ cosine  │ │ limits ·│
                 └──────────┘ └─────────┘ │ locks   │
                                          └─────────┘
```

**Non-standard local ports on purpose** (5442/6390): this machine runs other projects'
Postgres/Redis on the defaults, and binding those made the app silently talk to the
wrong database once. Dedicated ports make that class of bug impossible.

**Two runtimes, one contract.** The browser holds a JWT and speaks only
[API_CONTRACT.md](API_CONTRACT.md). Everything AI-related happens server-side; the
browser never sees an API key. The one deliberate exception: text-to-speech runs in the
browser (`SpeechSynthesis`) because server-side audio *output* is blocked by the
OpenRouter account's data policy — see §5.

---

## 2. The AI Router

**Nothing in the app names a model.** Callers name a *task*; the router resolves it.

```
caller ──► complete(task_type=QUIZ_GENERATE, messages)
              │
              ▼
   ai_routes table (DB, admin-editable, seeded from DEFAULT_ROUTES)
              │  primary_model · fallbacks[] · params
              ▼
   try primary ──429/5xx/timeout/404──► try fallback #1 ──► fallback #2 ─► AllModelsFailed
       │ success                                                            (503, typed)
       ▼
   record AIUsage row (tokens, micro-USD cost, latency, cache-hit, fallback-used)
   optionally cache result in Redis (deterministic tasks: translate 30d, vocab 30d)
```

Files: `app/ai/router.py` (the loop), `app/ai/tasks.py` (taxonomy + defaults),
`app/ai/openrouter.py` (LangChain `ChatOpenAI` bound to OpenRouter, model catalog, pricing).

Eleven routable tasks: `conversation`, `grammar_explain`, `translate`, `vocab_example`,
`quiz_generate`, `writing_evaluate`, `content_generate`, `pronunciation_score`, plus three
**non-chat** tasks (`embedding`, `speech_to_text`, `text_to_speech`) that resolve through
the same table but dispatch to dedicated endpoints — `router.complete()` refuses them so
audio bytes can't be sent to a chat endpoint by mistake.

Two hard-won behaviours:

- **`stream_usage=True`** on the LangChain client — without it, streamed responses carry
  no token counts and every cost reads $0 forever.
- **Route self-healing** (`heal_stale_routes`, on boot): model catalogs churn; a stored
  primary that no longer exists upstream is re-pointed to the current default — but only
  when `updated_by IS NULL`, so an admin's deliberate pin is never overwritten.

Admin surface: `GET/PUT /api/v1/admin/ai-routes` + `GET /api/v1/admin/models` (live
catalog with pricing). A model swap is a runtime config change, no redeploy — verified.

---

## 3. Flow: a tutor chat turn

`POST /api/v1/chat` → `text/event-stream`. Implementation: `app/ai/agent.py` +
`app/api/v1/chat.py`. Event order is contract (§2 of API_CONTRACT.md) and asserted in tests.

```
learner message
   │
   ├─ rate limit + monthly quota (Redis) ── 429/403 before any model spend
   ├─ persist user Message; injection heuristic → log + system prompt re-asserted
   │
   ├─► SSE: start {thread_id, message_id, model}
   ├─► SSE: status "Searching the knowledge base…"
   │
   ├─ A/B: assign_arm(user_id) → retrieval strategy (stable per user)     §8
   ├─ retrieve(query) → hybrid search → passages                          §4
   ├─ record RagEvent (arm, n_results, top_score, latency)
   ├─► SSE: sources [{id, title, snippet, score}]
   │
   ├─ system prompt = TUTOR_SYSTEM_PROMPT.format(cefr, native_language,
   │       target_language) + fenced/scrubbed passages                    §6, §11
   ├─ tools = build_tools(db, user)   (per-request, user-scoped)          §7
   │
   ├─ LangChain create_agent(llm, tools, prompt) → astream_events(v2)
   │     on_tool_start  ──► SSE: tool_call {name, args} + status
   │     on_tool_end    ──► SSE: tool_result {result, ms}
   │     model tokens   ──► SSE: token {text}   (per chunk)
   │     model failure  ──► next model in chain; if text already streamed, stop
   │                        cleanly rather than duplicate output
   │
   ├─ persist assistant Message {content, model, sources, tool_calls, usage}
   ├─ record AIUsage
   ├─► SSE: usage {tokens_in/out, cost_usd, latency_ms}
   └─► SSE: done          (or error {code, message} — the stream never just dies)
```

Wire-format details that will bite anyone who touches this code, all pinned by
`tests/test_sse_wire_format.py`:

- `data:` payloads **must be `json.dumps`-ed** — `sse_starlette` renders bare dicts with
  `str()`, producing single-quoted Python reprs that `JSON.parse()` rejects.
- The server emits **CRLF** line endings; clients must normalise before splitting frames.
- Tool `args` are taken from `on_tool_start` (fully parsed), not from streamed chunks
  (which carry incrementally-empty args).

Grammar-flavoured questions route to the stronger reasoning model (`grammar_explain`),
everything else to the cheaper `conversation` model — `pick_task()` in `agent.py`.

---

## 4. Flow: RAG

### Ingestion (admin-only)

```
POST /admin/documents (file)  or  /admin/documents/link (url | youtube | rss)
   │  validate: extension/size (streamed to var/uploads), SSRF guard for URLs
   ▼
Document row (status=pending) ──► Redis queue ──► worker (app/workers/ingest.py)
                                   (or inline asyncio task if Redis is down)
   ▼
parse (app/rag/parsers.py)         pdf/docx/epub/md/html/txt · web (readability)
   │                               youtube (transcript) · rss (fan-out to items)
   ▼
chunk (app/rag/chunker.py)         heading-aware, ~600 tokens, 15% overlap,
   │                               page attribution preserved
   ▼
embed (app/ai/embeddings.py)       OpenRouter /embeddings, batch 64,
   │                               text-embedding-3-small (1536d) — dimension
   │                               asserted at first call, not discovered later
   ▼
Qdrant upsert (payload: chunk_id, document_id, title, text, page, cefr, skill)
Chunk rows in Postgres (text is source of truth; Qdrant is a derived index)
   ▼
Document: status=ready · chunk_count · reading_minutes · content_md (for the Reader)
   (any failure → status=failed + human-readable error; never stuck in processing;
    duplicate content_hash → failed as "duplicate of …" without re-embedding)
```

**Automated updates**: `app/workers/scheduler.py` (`python -m app.workers.scheduler`)
polls registered RSS feeds when due (min 15-min politeness floor), ingests only items
above the last-seen GUID, under a Redis single-runner lock. Verified live with Deutsche
Welle's feed.

### Retrieval (`app/rag/retriever.py`)

```
query ──► embed_query ──► Qdrant cosine top-k ─────────┐  dense arm
      └─► BM25 (rank-bm25) over Chunk rows (SQL-filtered│  keyword arm
           candidate pool, ORDER BY for determinism)    │
                                                        ▼
                Reciprocal Rank Fusion  score = Σ 1/(60 + rank)
                                                        │
                     top-k RetrievedChunk (dense_score, keyword_score, fused score)
```

Why RRF and not score mixing: cosine (~0.7) and BM25 (~15) live on unrelated scales;
rank-based fusion is scale-free. The same reasoning shapes the A/B metrics (§8).

Retrieval **never raises on empty** and is **not filtered to the learner's exact CEFR
level** — an equality filter left C1 learners matching nothing in an A1/A2 corpus.
Level-appropriateness is the prompt's job.

Both halves degrade independently: a down Qdrant thins results to keyword-only, and
vice versa, with a logged warning.

---

## 5. Flow: speaking practice

`POST /api/v1/speaking/turn` (multipart: audio + scenario) → SSE. Implementation:
`app/api/v1/speaking.py`, `app/ai/audio.py`, `app/services/pronunciation.py`.

```
browser MediaRecorder (audio/webm)
   │ multipart upload (≤20 MB, checked)
   ▼
STT: multimodal chat call (gemini-2.5-flash + input_audio part)          SSE: transcript
   │   — NOT the dedicated /audio/transcriptions endpoint: that whole
   │     endpoint family is blocked on restrictive-data-policy accounts;
   │     an ordinary chat call works wherever chat works. transcribe()
   │     picks the path by model id, so whisper-* still routes dedicated.
   ▼
role-play reply (conversation task, in-character persona, German only)   SSE: token*
   ▼
scoring                                                                   SSE: scores
   ├─ grammar: LLM judge (pronunciation_score task), corrections
   │           explained in the learner's NATIVE language          §6
   ├─ fluency: mechanical — words/min vs CEFR band + filler density
   └─ pronunciation: transcript-quality proxy, ALWAYS flagged
               pronunciation_is_approximate=true (no phoneme aligner —
               the UI must show guidance, not a grade)
   ▼
TTS: server tries the text_to_speech route; on the account-policy 404 it
     raises SpeechUnavailable → SSE: audio {use_browser_tts: true, text,   SSE: audio
     lang: "de-DE"} and the BROWSER speaks the reply (SpeechSynthesis,
     German voice, primed voice list, rate 0.95). If the account later
     allows audio output, the same event carries data_uri instead —
     zero frontend change.
   ▼
persist Messages · record usage (chat + STT accounted separately)         SSE: usage, done
```

The learner's transcript is **fenced as untrusted data** before both the reply and the
grading calls — a learner can simply *say* "ignore the examiner instructions" (§11).

---

## 6. Native language ↔ target language

The product promise: *ask in your language, learn German.* Implemented end-to-end and
verified live in Turkish, Spanish, Urdu (RTL) and English.

- **Profile fields** (`users.native_language`, `users.target_language`, defaults en/de)
  set via `PATCH /me`, validated against `app/ai/languages.py`:
  - 20 native languages;
  - target languages must be `fully_supported` — Spanish/French/Italian are scaffolded
    but **refused** (422) until each has a conjugation engine + curated dictionary,
    because a tutor that invents grammar is worse than one that declines.
- **Every feedback surface speaks the native language** — the model is told the language
  *by name* and explicitly instructed **not to mirror the language of the question**
  (the observed failure: ask in German → whole answer in German):

  | Surface | Mechanism |
  |---|---|
  | Tutor chat | `TUTOR_SYSTEM_PROMPT.format(native_language=…, target_language=…)` |
  | Writing corrections | `evaluate_writing(native_language=…)` |
  | Quiz explanations | `generate_quiz(native_language=…)` |
  | Speaking corrections | `_grammar_score(native_language=…)` |
  | Dictionary glosses | curated grammar + machine-translated gloss (below) |

  German examples always stay German — a learner must see the real language.
- **Dictionary glosses** (`app/ai/tools/dictionary.py`): the ~120 curated entries are
  hand-verified for *grammar* (gender/plural/IPA) but English-only in meaning. On lookup,
  missing gloss languages are filled by a cached `translate` call (`_ensure_glosses`) —
  *Tisch → masa* for a Turkish learner — merged requested-language-first. The gloss is
  the one field safe to machine-translate; failure degrades to English, never to a
  failed lookup. `/tools/lookup-word` defaults to the learner's own languages when the
  client passes none.
- **Format-string trap** (regression-tested): prompts that embed literal JSON examples
  must brace-escape them — `.format()` treating `{"grammar": …}` as a replacement field
  silently degraded every speaking score to a neutral 0.7 with no corrections.

Known gap: the frontend has no native-language picker yet; the API is ready.

---

## 7. Tool calling

`app/ai/tools/registry.py` → `build_tools(db, user)` — built **per request**, closing
over the session and user so a tool cannot touch another user's rows (the
`save_vocabulary` schema has no user field at all; identity comes from the closure).

| Tool | Backing | Why it exists |
|---|---|---|
| `search_knowledge_base` | hybrid retriever | RAG on demand mid-conversation |
| `lookup_word` | curated dict → LLM fallback | gender/plural/IPA with provenance (`source: dictionary\|llm`) |
| `conjugate_verb` | **deterministic rule engine** (`conjugation.py`) | a wrong conjugation taught confidently is the worst failure mode; solved problems shouldn't be delegated to a model |
| `generate_quiz` | structured JSON call | answer key stripped before the model/client ever sees it |
| `evaluate_writing` | structured JSON call | span-level corrections |
| `save_vocabulary` | DB write + SM-2 card | side-effect tool, closure-scoped |

Every tool has a Pydantic `args_schema` (the graded *input validation* — bad args are
rejected before execution) and returns an error *string* on failure rather than raising,
because an exception inside the agent loop would kill the SSE stream.

Structured outputs (`app/ai/structured.py`): strict-JSON instruction → tolerant parse
(strip fences, outermost object) → Pydantic validation → **exactly one repair retry**
feeding the validation error back → typed failure.

---

## 8. A/B testing

`app/rag/experiments.py` + `experiment_configs` / `rag_events` tables + three admin
endpoints (`GET/PUT /admin/experiments*`).

- **Assignment** is a salted SHA-256 bucket of the user id — the same learner always
  gets the same arm (random-per-request would make per-user outcomes uninterpretable,
  and Python's `hash()` is process-salted so it can't be used). Weights normalise, so
  `{hybrid: 1, dense: 3}` means 25/75.
- **Events, not re-runs**: each retrieval records what the learner actually received
  (`arm, n_results, top_score, latency`); results aggregate those rows.
- **Scale-free ranking only.** A live run "proved" dense wins by mean score — cosine
  ~0.74 vs RRF ~0.03 — which is a unit mismatch, not a result. Arms rank by
  zero-result rate then usable-result count; the raw score is exposed only as
  `mean_top_score_within_arm`. Cross-arm *relevance* belongs to the offline eval (§13).
- Fewer than 30 events → `winner: null` with an explicit "too few events" note.

---

## 9. MCP

Both directions of the Model Context Protocol (`app/mcp/`, SDK v2, stdio transport):

- **Servers** (tools *as* MCP): `python -m app.mcp.server` exposes `conjugate_verb`,
  `lookup_german_word`, `search_knowledge_base`, `german_examples`;
  `python -m app.mcp.data_server` is a DB-free German-data server (Wiktionary DE parse
  for gender/plural/IPA, Wikipedia DE search, Tatoeba example sentences — keyless public
  APIs, Redis-cached 7 days, every failure degrades to empty rather than raising).
- **Client** (`app/mcp/client.py`): reads `MCP_SERVERS` (JSON env), connects over stdio,
  adapts advertised tools into LangChain `StructuredTool`s (JSON-schema → Pydantic).
  Defaults to our own data server so it works with zero setup; pointing it at any public
  MCP server is config only. Unreachable servers and malformed schemas are skipped with
  a warning, never fatal.

The Wiktionary parser is fixture- *and* live-tested; live data exposed three parser bugs
(prose captured as a plural, section headings as POS, syllable dots in plurals) that
fixtures alone missed — the regression tests now encode real Wiktionary shapes.

---

## 10. Data model & migrations

18 tables (see `backend/app/db/models.py`; all timestamped, UUID PKs):

```
users ─┬─ threads ── messages (sources/tool_calls/usage JSONB)
       ├─ vocabulary ── flashcards (SM-2 state)
       ├─ quizzes (answer key server-side) · writing_submissions
       ├─ topic_stats (weak spots) · activity (streaks)
       └─ rag_events (A/B outcomes)
documents ── chunks (text + optional pgvector column)
feed_sources (RSS scheduler state)
ai_routes · ai_usage · experiment_configs · alembic_version
```

**Migrations are Alembic, never `create_all()`.** `create_all` creates missing *tables*
but silently ignores new columns on existing ones — that exact no-op let the app boot
and then 500 on `column users.native_language does not exist`. Now:

- boot runs `alembic upgrade head` (worker thread; the command API is sync);
- `alembic.ini` carries **no URL** — it comes from `app.core.config` (env);
- `migrations/env.py` creates the pgvector extension first and **commits explicitly**
  (the extension DDL opens a transaction, which otherwise makes Alembic assume external
  management and silently apply nothing);
- `migrations/script.py.mako` pre-imports `pgvector.sqlalchemy` (autogenerate references
  it without importing it);
- `tests/test_migrations.py::test_no_model_drift` fails the suite if models and schema
  diverge — the guard that would have caught the original bug.

Workflow: edit models → `alembic check` → `alembic revision --autogenerate -m "…"` →
**read the file** → `alembic upgrade head`.

Prod swap is env-only: `DATABASE_URL` → managed Postgres, `QDRANT_URL(+API_KEY)` →
Qdrant Cloud, `REDIS_URL` → managed Redis. Local JWT auth is isolated behind
`decode_token()` in `core/security.py` for a later JWKS swap.

---

## 11. Security model

| Threat | Defence | Where |
|---|---|---|
| Prompt injection via KB | passages **and titles** scrubbed (override phrasing redacted, fence tags stripped) then wrapped in a `<knowledge_base>` data fence; fixed system prompt | `app/ai/prompts.py` |
| Injection via speech/user text | transcript fenced before reply *and* grading; injection-looking messages logged, prompt re-asserted (not hard-blocked — innocent questions match too) | `speaking.py`, `agent.py` |
| SSRF on URL import | scheme/host/IP validation incl. DNS resolution, private/reserved/link-local ranges rejected, **re-validated on every redirect hop** (max 5) — blind refusal lost 45/86 real articles; blind following would defeat the guard | `app/rag/parsers.py` |
| Cross-user data access | `user_id` predicate in the same statement for every owned read/write; 404 (not 403) on misses; tools closure-scoped | all `api/v1/*`, `registry.py` |
| Quiz answer leakage | `expected` persisted server-side only; stripped from generate responses **and** from tool results the model sees; graded server-side; double-submit rejected | `quiz.py`, `structured.py` |
| Cost abuse | per-user+IP rate limits, monthly AI quota (`/tools/lookup-word` counts too — it can trigger billed calls), 30-day caches for deterministic tasks, size caps on uploads/audio | `core/cache.py` |
| Secret exposure | env-only secrets; no key/password in any response, log line, or `alembic.ini`; prod boot refuses `changeme123` and weak JWT secrets | `core/config.py` |
| Auth | bcrypt (direct — passlib is unmaintained and breaks with bcrypt 5.x), JWT verified per request, role re-read from DB rather than trusted from the token | `core/security.py`, `core/deps.py` |

---

## 12. Observability, cost & limits

- **structlog** everywhere: console in dev, JSON in prod; request-id middleware ties a
  client-visible error to its log line.
- **`ai_usage`** — one row per model call (tokens, micro-USD, latency, cache-hit,
  fallback-used) → `/admin/usage` (by day/model/task/user) and each learner's own
  spend in `/analysis`.
- Fallback spikes in logs = degraded primary model; boot-time healing fixes retired ones.
- Rate limits and quotas degrade **open** if Redis is down (availability over perfect
  enforcement in dev) — a deliberate, logged trade-off.

---

## 13. Evaluation harness

`app/eval/` + `python -m scripts.eval_rag [--strategy hybrid|dense] [--no-judge]`.

- Deterministic IR metrics over a 14-case golden set grounded in the seeded corpus
  (2 cases deliberately unanswerable): hit-rate, MRR, nDCG@k, context precision/recall.
  Retrieved chunk-titles are **deduplicated before scoring** — chunk-level retrieval
  otherwise repeats one document six times and pushes nDCG past 1.0 (observed 3.3,
  impossible by definition; guarded in the metric *and* the runner).
- LLM-judged faithfulness + answer-relevancy, judge discrimination verified
  (grounded 1.0 / hallucinated 0.0 / off-topic 0.0 / honest refusal 1.0).
- One event loop for the whole run — two `asyncio.run` calls bound the DB engine to a
  dead loop and silently degraded the dense arm mid-comparison.
- The `ragas` package is incompatible with LangChain 1.x (imports a removed module) —
  metrics are implemented directly, which the task text permits ("RAGAs or otherwise").

---

## 14. How to extend

**Add a teachable language** — the honest checklist (`app/ai/languages.py`):
1. conjugation/inflection engine + tests (grammar must be computed, not guessed);
2. curated core dictionary (~100 words, hand-verified genders);
3. seeded corpus for RAG;
4. speaking scenarios;
5. Wiktionary host + Tatoeba code for the MCP data tools;
6. flip `fully_supported=True` — validation and prompts pick it up automatically.

**Add a tool**: function in `app/ai/tools/`, Pydantic `args_schema`, register in
`build_tools()`, return error strings (never raise), add a `ToolResultCard` renderer
in the frontend, test arg rejection + the happy path.

**Add/point a model**: `PUT /admin/ai-routes/{task}` at runtime, or edit
`DEFAULT_ROUTES` for new installs. Non-chat modalities go in `NON_CHAT_TASKS`.

**Add a schema change**: models → `alembic revision --autogenerate` → read it → upgrade.
The drift test fails CI if you forget.

**Add an experiment arm**: extend the `arms` validator in `admin.py` and the strategy
handling in `retriever.py`; assignment/reporting need no changes.

---

## 15. Decision log

| Decision | Why |
|---|---|
| Deterministic conjugation engine over LLM | wrong grammar taught confidently is the product's worst failure; German weak-verb morphology is rule-complete and strong verbs are a finite table |
| Multimodal-chat STT instead of `/audio/transcriptions` | dedicated audio endpoints 404 on restrictive-data-policy accounts (verified, not overridable per request); chat-with-audio works wherever chat works |
| Browser TTS as the audio-output path | audio-*output* models are entirely blocked on this account class; `SpeechSynthesis` is free, has German voices, keeps learner audio on-device; server path auto-activates if ever unblocked |
| RRF for hybrid + scale-free A/B ranking | cosine and BM25 (and RRF) scores are unit-incompatible; ranks are not |
| Alembic from boot, `create_all` banned | silent-no-op schema changes produced a production-class 500; drift is now a failing test |
| Redis-optional degradation | dev ergonomics: cache/limits/queue all no-op gracefully; the scheduler logs when it runs unlocked |
| Answer keys never serialised client-ward | grading is a server concern; a key in the payload is a cheat sheet |
| `pronunciation_is_approximate: true` | no phoneme aligner exists here; presenting a proxy as a grade would be dishonest — the contract obliges the UI to label it guidance |
| Spanish/French/Italian refused, not half-taught | scaffolded in the registry but 422 until they meet the same bar as German |
| Feedback in the learner's native language everywhere | feedback the learner cannot read is feedback that does not exist; German spans preserved so the learner sees the real language |
