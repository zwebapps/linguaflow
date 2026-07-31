# LinguaFlow AI — Backend

FastAPI + LangChain + OpenRouter. Local Postgres/Qdrant/Redis via Docker; the same
code runs on Render + Supabase + Qdrant Cloud by changing env vars only.

## Quick start

```bash
cd backend
cp .env.example .env
# then put your key in .env:  OPENROUTER_API_KEY=sk-or-...
```

Start the local infrastructure:

```bash
docker compose up -d
```

Install and run:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

First start creates the schema, seeds the AI routing table, creates the
bootstrap admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`, and **auto-ingests the
starter library** under `seed/` (local/ci) so learners see readings immediately.

You can re-run ingestion manually:

```bash
python -m scripts.seed_kb
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/readyz
- Admin login: `admin@linguaflow.dev` / the `ADMIN_PASSWORD` from `.env`

> The admin email must be a **real TLD**. `email-validator` rejects reserved names
> like `.local`, so an `admin@…​.local` account exists in the DB but can never log
> in through the API.

## Voice works — with a split architecture

Verified live 2026-07-30 on a real org account:

| Half | How | Status |
|---|---|---|
| **Speech → text** | `POST /chat/completions` with an `input_audio` part on a multimodal model (`google/gemini-2.5-flash`) | ✅ Works. Transcribed German test audio verbatim in ~1.3 s. |
| **Text → speech** | Browser `SpeechSynthesis` (`de-DE`) | ✅ Works, free, audio stays on device |
| *Text → speech, server-side* | `POST /audio/speech` | ❌ Blocked — see below |

**Why the split.** The dedicated `/audio/*` endpoints and every audio-*output* model
return `404 "No endpoints available matching your guardrail restrictions and data
policy"` on accounts with a restrictive data policy — and allowed chat models reject
`modalities: ["audio"]` outright. Rather than depend on that, STT rides an ordinary
chat call (works wherever chat works) and TTS happens in the browser. The turn emits
`audio: {use_browser_tts: true, text, lang}` and the client speaks it.

To enable server-side TTS anyway, allow providers that may train on request data at
<https://openrouter.ai/settings/privacy> (an **org admin** may have to lift an
org-level guardrail — it is not overridable per request; I tested). Weigh it up:
that permits third parties to train on what you send, which for voice means real
learner audio. `audio.synthesize()` raises `SpeechUnavailable` and the client falls
back automatically, so nothing breaks either way.

## Layout

```
app/
├─ main.py              app factory, middleware, /healthz /readyz
├─ core/                config · errors · security(JWT) · deps · cache(Redis) · logging
├─ db/                  SQLAlchemy models + session
├─ ai/
│  ├─ tasks.py          task taxonomy + per-task model policy
│  ├─ router.py         ★ AI Router: task → model, fallbacks, cache, usage
│  ├─ openrouter.py     LangChain ChatOpenAI → OpenRouter, catalog, cost
│  ├─ prompts.py        domain tutor prompt + prompt-injection guard
│  ├─ agent.py          LangChain tool-calling agent, streamed as SSE
│  └─ tools/            conjugation engine · dictionary · tool registry
├─ rag/
│  ├─ contracts.py      the frozen RAG interface
│  ├─ parsers.py        pdf/docx/epub/md/html/web/youtube/rss + SSRF guard
│  ├─ chunker.py        structure-aware chunking
│  ├─ embedder.py       local sentence-transformers (free) or hosted
│  ├─ vector_store.py   Qdrant | pgvector behind one interface
│  ├─ retriever.py      dense + hybrid (BM25 + RRF) search
│  └─ ingest.py         parse → chunk → embed → upsert
├─ api/v1/              auth · chat · tools · library · vocab · flashcards
│                       quiz · writing · analysis · admin
├─ services/            bootstrap · srs · export · feeds
└─ workers/ingest.py    background ingestion consumer
```

## How model switching works

Nothing in the app names a model. Callers name a **task**
(`grammar_explain`, `conversation`, `quiz_generate`, …). The AI Router resolves
task → policy from the `ai_routes` table, tries the primary model, and falls
through the fallback chain on rate-limits/timeouts/5xx. An admin re-points a task
at a different model from `PUT /api/v1/admin/ai-routes/{task_type}` — no redeploy.

Every call writes an `ai_usage` row (tokens, cost, latency, cache hit, whether a
fallback was used), which powers the cost dashboard and quota enforcement.

## Switching to production

No code changes — only env:

| Local | Production |
|---|---|
| `DATABASE_URL` → docker Postgres | Supabase connection string |
| `QDRANT_URL` → localhost:6333 | Qdrant Cloud URL + `QDRANT_API_KEY` |
| `REDIS_URL` → localhost:6379 | Render Key-Value / Upstash |
| `EMBEDDING_BACKEND=local` | `openrouter` (or keep local) |
| `VECTOR_BACKEND=qdrant` | `qdrant` or `pgvector` |

Auth is local JWT in V1. Swapping to Supabase Auth means replacing
`decode_token()` in `core/security.py` with JWKS verification — the rest of the
app only sees `TokenClaims`.

## Database migrations

Schema changes go through **Alembic**, never `create_all()` — that only creates
missing *tables* and silently ignores new columns on existing ones, which once let
the app boot and then 500 on a column that was never added.

```bash
alembic upgrade head                                   # apply (the app also does this on boot)
alembic revision --autogenerate -m "add x to y"        # after changing a model
alembic check                                          # fail if models and DB have drifted
alembic downgrade -1                                   # roll back one revision
alembic history                                        # what exists
```

The workflow after editing `app/db/models.py` is: autogenerate → **read the generated
file** → `upgrade head`. Autogenerate is a first draft, not an oracle: it misses table
renames and data migrations, and it writes `pgvector.sqlalchemy...` for the embedding
column (the import is pre-added via `migrations/script.py.mako`).

`tests/test_migrations.py::test_no_model_drift` fails the suite if a model change has
no matching migration — that is the guard that would have caught the original bug.

The connection URL comes from `app.core.config`, not `alembic.ini`; never put a real
one (with a password) in the ini file.

## Commands

```bash
pytest                    # hermetic — no network, no live LLM calls
ruff check app            # lint
mypy app                  # types
alembic check             # schema/model drift
```
