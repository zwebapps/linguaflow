# DeutschFlow AI — German CEFR Tutor

An AI-native platform for learning German (A1–C1): a **RAG-grounded, tool-calling tutor**
that explains in the learner's own language, plus reading, quizzes, writing evaluation,
spoken practice with feedback, flashcards, and progress analytics.

Built with **Next.js** (frontend) · **FastAPI + LangChain over OpenRouter** (backend) ·
**Qdrant** (vectors) · **PostgreSQL** (data) · **Redis** (cache/limits).

> Learners *talk in their native language and learn German*: a Turkish learner asks
> "Almancada Dativ ne zaman kullanılır?" and gets a Turkish explanation with German
> examples, Turkish word glosses (*Tisch → masa*), Turkish writing corrections, and
> Turkish quiz explanations. 20 native languages supported.

---

## Quick start

Prerequisites: Docker, Python 3.11, Node 20+, an [OpenRouter](https://openrouter.ai/keys) API key.

**1. Infrastructure** (Postgres :5442, Qdrant :6333, Redis :6390 — non-standard ports on purpose):

```bash
cd backend
cp .env.example .env          # then set OPENROUTER_API_KEY=sk-or-...
docker compose up -d
```

**2. Backend** (:8000):

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

First boot runs Alembic migrations, seeds the AI routing table, creates the admin
account, and (with an API key present) ingests a starter German knowledge base.

**2b. Ingestion worker** (required — uploads stay `pending / 0 chunks` forever
without it; the API only *enqueues* to Redis, this process consumes):

```bash
python -m app.workers.ingest
```

**3. Frontend** (:3010):

```bash
cd ../frontend
npm install
npm run dev -- --port 3010
```

**4. Sign in** at http://localhost:3010

| Account | Email | Password |
|---|---|---|
| Learner | `learner@deutschflow.ai` | see `DEMO_LEARNER_PASSWORD` in `.env` |
| Admin | `admin@deutschflow.dev`* | `ADMIN_PASSWORD` in `.env` |

*or whatever `ADMIN_EMAIL` is set to — must be a real TLD; `.local` addresses fail email validation.

API docs: http://localhost:8000/docs · Health: http://localhost:8000/readyz

---

## What it does

### For learners
- **AI Tutor chat** — streamed answers grounded in the German knowledge base, with
  source citations, visible tool calls, per-turn token cost, and conversation history.
- **Native-language learning** — set your language once (`tr`, `es`, `ur`, `ar`, `hi`, … 20 total);
  explanations, corrections, quiz feedback and dictionary glosses all arrive in it.
- **Reader** — graded German texts; tap a word for gender/plural/IPA + gloss in your language.
- **Quizzes** — RAG-grounded, graded server-side (the answer key never reaches the client).
- **Writing evaluation** — CEFR estimate, scores, span-level corrections explained in your language.
- **Speaking practice** — record German speech; server transcribes (multimodal STT), a
  role-play partner replies, grammar/fluency are scored, the reply is spoken via browser TTS.
- **Flashcards** — SM-2 spaced repetition seeded from words you save.
- **Progress analytics** — per-skill scores, weak spots, CEFR trend, streaks, your AI spend.

### For admins
- **Knowledge base** — upload PDF/EPUB/DOCX/MD/HTML/TXT or import URLs/YouTube/RSS;
  automatic chunk → embed → index with status tracking and SSRF-guarded fetching.
- **Auto-updating corpus** — registered RSS feeds are polled on schedule; new articles
  ingest themselves (verified with Deutsche Welle: 86 articles).
- **Model routing** — every AI task (chat, quiz, STT, embeddings, …) maps to a model +
  fallback chain, editable at runtime; dead models self-heal on boot.
- **A/B testing** — split traffic between retrieval strategies per-user-stable; results
  aggregated from what learners actually received.
- **Usage & cost** — per-model/task/day token and dollar accounting.

### For machines
- Two **MCP servers** (`python -m app.mcp.server`, `python -m app.mcp.data_server`)
  expose the domain tools over the Model Context Protocol; an **MCP client** adapts
  any external MCP server's tools into LangChain tools via config.

---

## Course requirements → where implemented

| Requirement | Where |
|---|---|
| **RAG** — KB, embeddings, chunking, similarity search | `backend/app/rag/` — structure-aware chunking, OpenRouter embeddings, Qdrant cosine search; seeded German corpus in `backend/seed/` |
| **Tool calling (≥3)** | `backend/app/ai/tools/registry.py` — **6 tools**: `search_knowledge_base`, `lookup_word`, `conjugate_verb` (deterministic rule engine), `generate_quiz`, `evaluate_writing`, `save_vocabulary` |
| **Domain specialisation** | German CEFR tutoring; domain prompts in `app/ai/prompts.py`; security below |
| **LangChain + OpenRouter** | `app/ai/openrouter.py` (`ChatOpenAI` → OpenRouter) + `app/ai/agent.py` (LangChain 1.x `create_agent`) |
| **Error handling / validation** | Typed error envelope (`app/core/errors.py`), model fallback chains, Pydantic on every request body *and* every tool argument |
| **UI** (Next.js) | `frontend/` — sources panel, tool chips, streaming with stage indicators, cost footer |

**Optional tasks implemented** — Easy 4/4 · Medium 9/10 · Hard 6/7:
multi-model routing, prompt-injection protection, auth + personalisation, token/cost
display, tool-result visualisation, PDF/CSV/JSON/MD export, rate limiting + quotas,
logging/monitoring, real-time + automated KB updates (RSS scheduler), **hybrid search**
(BM25 + dense with Reciprocal Rank Fusion), **A/B testing of RAG strategies**,
**multi-language support**, **analytics dashboard**, **tools as MCP servers**, and a
**RAG evaluation harness** (`python -m scripts.eval_rag` — nDCG/MRR/precision/recall +
LLM-judged faithfulness; RAGAs itself is incompatible with LangChain 1.x, so the
metrics are implemented directly, which the task permits).

## Security measures

- **Prompt injection**: retrieved passages *and their titles* are scrubbed and fenced as
  data (`app/ai/prompts.py`); learner speech is fenced before grading; injection-looking
  user messages are logged and the system prompt re-asserted.
- **SSRF**: URL imports resolve DNS and reject private/reserved ranges on **every
  redirect hop** (`app/rag/parsers.py`).
- **Isolation**: every user-owned query is scoped by `user_id` in the statement; quiz
  answer keys never leave the server; tools can only write the calling user's rows.
- **Cost abuse**: per-user rate limits + monthly AI quotas (Redis), response caching for
  deterministic tasks, upload/audio size caps.
- **Secrets**: env-only (`.env` is gitignored); production refuses default admin
  password and weak JWT secrets at boot.

## Testing

```bash
cd backend && source .venv/bin/activate
pytest          # 356 tests — hermetic: no network, no live LLM calls
ruff check app tests scripts
alembic check   # model ↔ schema drift guard
python -m scripts.eval_rag --no-judge   # RAG eval: hybrid vs dense
```

## Repository layout

```
├── README.md            ← you are here
├── ARCHITECTURE.md      ← as-built architecture + flow diagrams (start here to modify)
├── API_CONTRACT.md      ← the frozen frontend↔backend contract (SSE events, shapes)
├── FRONTEND_SPEC.md     ← frontend build spec / slice checklist
├── backend/             ← FastAPI · LangChain · RAG · MCP · Alembic · 356 tests
└── frontend/            ← Next.js app
```

## Known limitations & next steps (reflection)

- **No native-language picker in the UI yet** — the API is ready
  (`PATCH /me {"native_language": "tr"}`); the dropdown is the next frontend task.
- **Server-side TTS is account-gated** on OpenRouter data policy; the app falls back to
  browser `SpeechSynthesis` automatically (and tells the client to). STT works server-side.
- **Pronunciation score is an approximation** derived from transcript quality — it is
  flagged `pronunciation_is_approximate: true` and must be displayed as guidance, not a grade.
- **Only German is teachable** — Spanish/French/Italian are scaffolded but deliberately
  refused until each has a conjugation engine + curated dictionary (a wrong-but-confident
  grammar engine is worse than none).
- **Curated dictionary is ~120 words**; other words fall back to LLM lookups, whose noun
  genders are marked `source: "llm"` so the UI can show provenance.
- Upload size caps run after Starlette spools multipart to disk; a reverse-proxy body
  limit is recommended in production.
