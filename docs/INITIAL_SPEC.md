> **Historical document** — the pre-build specification (planned: Supabase/Vercel/Render). The system as actually built is documented in [../ARCHITECTURE.md](../ARCHITECTURE.md); where they disagree, the as-built doc wins.

# LinguaFlow AI — Product & Architecture Documentation

> **An AI-native German learning platform — a digital language university, not a chatbot.**
> Reading · Listening · Speaking · Writing · Grammar · Vocabulary · AI Tutoring · Adaptive paths.

**Version:** 1.0 (Final) · **Status:** Buildable spec · **Last updated:** 2026-07-30

Deployment target (fixed):

| Layer | Provider |
|---|---|
| Frontend | **Vercel** (Next.js) |
| Backend / API | **Render** (FastAPI, Docker) |
| Database | **Supabase PostgreSQL** |
| Auth | **Supabase Auth** |
| Object storage | **Supabase Storage** |
| Vector DB / RAG | **Qdrant Cloud** (behind a swappable seam; **pgvector on Supabase** is a drop-in free alternative — see §8) |
| LLM gateway | **OpenRouter** (OpenAI-compatible) |
| LLM orchestration | **LangChain** (agent + tools + retriever + memory), in the FastAPI backend |
| CI/CD | **GitHub Actions** |

---

## Table of contents

1. [Product overview](#1-product-overview)
2. [User roles & permissions](#2-user-roles--permissions)
3. [Screen inventory](#3-screen-inventory)
4. [System architecture](#4-system-architecture)
5. [Multi-model AI switching (the AI Router)](#5-multi-model-ai-switching-the-ai-router)
6. [RAG pipeline](#6-rag-pipeline)
7. [Data model — PostgreSQL](#7-data-model--postgresql)
8. [Vector store — Qdrant](#8-vector-store--qdrant)
9. [API surface](#9-api-surface)
10. [Auth & security (Supabase)](#10-auth--security-supabase)
11. [Storage design (Supabase Storage)](#11-storage-design-supabase-storage)
12. [Frontend architecture](#12-frontend-architecture)
13. [Design system](#13-design-system)
14. [Deployment topology](#14-deployment-topology)
15. [CI/CD (GitHub Actions)](#15-cicd-github-actions)
16. [Environment configuration](#16-environment-configuration)
17. [Observability, cost & rate limiting](#17-observability-cost--rate-limiting)
18. [Subscription & billing model](#18-subscription--billing-model)
19. [Delivery roadmap](#19-delivery-roadmap)
20. [Repository layout](#20-repository-layout)
- [Appendix A — Task requirements coverage (admin vs end-user)](#appendix-a--task-requirements-coverage-admin-vs-end-user)

---

## 1. Product overview

LinguaFlow AI is a full-stack, AI-native platform for learning **any language**. Instead of landing on a
chat window, the learner lands on a **personalized dashboard** where AI is embedded across every
module — as a tutor, an examiner, a translator, a conversation partner, and a search engine over a
curated German knowledge base.

**Positioning**

| Competitor | Gap LinguaFlow fills |
|---|---|
| Duolingo | Gamified but shallow; no real tutoring or free-form practice |
| Babbel | Structured but static; limited personalization |
| DW Learn German | Great content, weak adaptivity |
| ChatGPT | Powerful AI, zero learning structure or progress model |

**Core loop:** structured content → AI-assisted practice → assessment → spaced repetition →
adaptive next lesson → progress tracking.

The product is one coherent experience built on five pillars:

1. **Content** — grammar, stories, vocabulary, listening, dialogues, culture, organized by CEFR (A1–C1).
2. **AI tutor** — context-aware explanations, examples, quizzes, and role-play grounded in RAG.
3. **Personal knowledge base** — notes, saved vocabulary, flashcards, bookmarks.
4. **Assessment** — writing evaluation, speaking scoring, adaptive quizzes with CEFR estimation.
5. **Progress** — per-skill mastery, streaks, achievements, recommended next steps.

---

## 2. User roles & permissions

| Role | Capabilities |
|---|---|
| **Student** | Learn, read, listen, speak, write, save vocabulary, take notes, use flashcards, chat with the AI tutor, take tests, and view feedback & analysis. **Cannot upload/ingest content.** |
| **Teacher / Creator** *(Phase 2)* | Author lessons/stories, publish learning packs to the marketplace, monitor enrolled students. |
| **Admin** | **Knowledge-base ingestion (upload books/docs, link web/YouTube/RSS resources)**, user management, content moderation, AI model/route configuration, analytics, cost dashboards. |

Roles are stored in `profiles.role` and enforced two ways:

- **Postgres Row-Level Security (RLS)** for every user-owned table (a student can only read/write their own rows).
- **API authorization guards** on the FastAPI side that check the decoded Supabase JWT `role` claim for admin/teacher endpoints.

---

## 3. Screen inventory

Grouped by area. Each screen names its primary data source and whether it calls the AI Router.

### Authentication & onboarding
| Screen | Notes | AI |
|---|---|---|
| Login | Email + OAuth (Google, GitHub) via Supabase Auth; password recovery | — |
| Sign-up | Email/OAuth; creates `profiles` row on first login (DB trigger) | — |
| Onboarding 1 — Goal | Travel / Work / University / Immigration / Personal | — |
| Onboarding 2 — Level | CEFR self-select A1–C1 (later refined by placement quiz) | — |
| Onboarding 3 — Style | Reading / Listening / Speaking / Writing / Balanced | — |
| Onboarding 4 — Daily goal | 10 / 20 / 30 / 60 min | — |

### Core learning
| Screen | Notes | AI |
|---|---|---|
| **Dashboard** | Continue learning, today's goal ring, stats, streak, recommended lesson. Chat is *one card*. | route (recommendations) |
| **Learning Library** | Searchable repository; filters by level + skill + category | search + RAG |
| **Story list** | Grouped by CEFR (A1…C1), counts per level | — |
| **Story detail** | Reading time, grammar focus, vocab count, "Start reading" | — |
| **Reading Mode** | Kindle-style reader; tap word → meaning, multilingual gloss (Hindi/Polish/…), audio, examples, save, "Ask AI" | translate + explain |
| **Grammar dashboard** | Topic tree by CEFR, per-topic progress | — |
| **Grammar lesson** | Intro · Rules · Examples · Common mistakes · Exercises · AI explanation · Quiz · Practice chat | explain + quiz |
| **Vocabulary dashboard** | Learned / Review today / Mastered / Needs practice | — |
| **Word detail** | Article, plural, pronunciation, examples, related words, AI explanation | explain |
| **Flashcards** | SM-2 / FSRS spaced repetition; Easy/Hard/Again | — |
| **Listening** | Audio player + transcript + vocab + quiz | quiz gen |
| **Speaking** | Voice role-play (STT → LLM → TTS); pronunciation/grammar/fluency scores | voice pipeline |
| **Writing** | Prompt → submit → grammar/vocab/CEFR score + suggestions + improved version | evaluate |
| **AI Tutor** | Lesson-aware assistant: Explain / Practice / Quiz / Conversation / Examples | route (all) |

### Personal & meta
| Screen | Notes | AI |
|---|---|---|
| Notes | Folders, pinned, markdown editor (images/audio/highlight), AI assist | assist |
| Progress | Level, per-skill %, weekly activity chart, achievements | — |
| **Feedback & Analysis** | Consolidated view of writing/speaking/quiz scores over time, CEFR trend, weak-spot breakdown & next-step recommendations | — |
| Global Search | Unified AI search across lessons, stories, vocab, notes | RAG |
| Settings | Profile, learning prefs, reading theme (light/dark/sepia/large), subscription | — |
| Marketplace *(Phase 2)* | Browse/buy teacher packs | — |
| Admin console | Users, content, AI routes, analytics, cost | — |
| **Admin — Knowledge Base** *(admin only)* | Upload books/docs or link resources (web/YouTube/RSS), tag CEFR/skill, register feeds, monitor ingest jobs, purge docs | ingest |

---

## 4. System architecture

```
                                   ┌──────────────────────────┐
                                   │        Learner            │
                                   └────────────┬─────────────┘
                                                │ HTTPS
                            ┌───────────────────▼────────────────────┐
                            │  Vercel — Next.js (App Router, React)   │
                            │  • SSR/ISR marketing + app shell        │
                            │  • Route handlers proxy to backend      │
                            │  • Supabase JS (auth session)           │
                            └───────┬───────────────────────┬─────────┘
                                    │ Supabase JWT           │ REST (Bearer JWT)
                                    │ (auth only)            │
                     ┌──────────────▼──────────┐   ┌─────────▼─────────────────────┐
                     │   Supabase              │   │  Render — FastAPI backend      │
                     │  • Auth (GoTrue)        │   │  • REST API / route handlers   │
                     │  • Postgres + RLS       │◄──┤  • AI Router (model switching) │
                     │  • Storage (S3-compat)  │   │  • RAG orchestrator            │
                     └─────────────────────────┘   │  • Learning engine / SRS       │
                                    ▲               │  • Background workers (ingest) │
                                    │               └───┬───────────────┬───────────┘
                                    │ verify JWT (JWKS) │               │
                                    │                   │ embeddings +  │ chat / vision /
                                    │                   │ search        │ tts-stt (via OpenRouter)
                          ┌─────────┴─────────┐  ┌──────▼────────┐  ┌───▼────────────────┐
                          │  Redis (cache/    │  │  Qdrant Cloud │  │   OpenRouter        │
                          │  rate-limit/queue)│  │  (vectors)    │  │  (LLM gateway →     │
                          └───────────────────┘  └───────────────┘  │   many models)      │
                                                                     └─────────────────────┘
```

**Key decisions**

- **Two runtimes, one auth.** Next.js on Vercel owns the UI and holds the Supabase session; FastAPI on Render owns all AI/RAG/learning logic. The browser talks to FastAPI directly with the Supabase JWT as a `Bearer` token; FastAPI verifies it against Supabase's JWKS. No secrets in the browser.
- **Supabase is the system of record** for users, content, progress, notes, vocab. **Qdrant holds only vectors + light payload** (never the source of truth).
- **OpenRouter is the single egress for all model calls** — one API key, one billing surface, model-agnostic. The AI Router (in FastAPI) decides *which* model per task.
- **Redis** (Render add-on or Upstash) does response caching, rate limiting, and a lightweight job queue for document ingestion.
- **Stateless backend**: horizontally scalable on Render; all state lives in Postgres/Qdrant/Redis/Storage.

---

## 5. Multi-model AI switching (the AI Router)

The single most important architectural feature. **The app never hardcodes a model.** Every AI
request is a *task* with a `task_type`; the **AI Router** maps task → model policy → OpenRouter
model id, with fallbacks. This keeps the app resilient to model deprecation, lets you tune
cost/quality per task, and makes A/B testing a config change, not a code change.

### 5.1 Task taxonomy

| `task_type` | What it does | Quality need | Latency need |
|---|---|---|---|
| `grammar_explain` | Deep grammar explanations, error correction | High reasoning | Relaxed |
| `translate` | Word/phrase translation, multilingual gloss | Multilingual, fast | Low |
| `vocab_example` | Generate example sentences | Medium | Low |
| `content_generate` | Stories, lessons, exercises (long) | Long context | Relaxed |
| `writing_evaluate` | Score essay + suggestions + rewrite | High reasoning | Relaxed |
| `conversation` | Free-form / role-play tutor chat | Balanced | Low–medium |
| `quiz_generate` | Structured quiz JSON | Medium, structured | Low |
| `speech_to_text` | Transcribe learner audio | Accuracy | Low |
| `text_to_speech` | Voice output | Naturalness | Low |
| `embedding` | Vectorize text for RAG/search | Consistent | Low |
| `vision_ocr` | Menu/handout photo → text (optional import) | Vision | Relaxed |

### 5.2 Routing policy (config, not code)

Routing lives in a versioned table `ai_routes` (and a seed file), so admins change it without a
deploy. Each task points at a **primary** model and an ordered **fallback** chain.

```jsonc
// seed: config/ai_routes.json  (mirrored into the ai_routes table)
{
  "grammar_explain":  { "primary": "anthropic/claude-3.7-sonnet",     "fallbacks": ["openai/gpt-4o", "google/gemini-2.0-flash"], "temperature": 0.3, "max_tokens": 1200 },
  "translate":        { "primary": "google/gemini-2.0-flash",         "fallbacks": ["openai/gpt-4o-mini"], "temperature": 0.2, "max_tokens": 400 },
  "vocab_example":    { "primary": "openai/gpt-4o-mini",              "fallbacks": ["google/gemini-2.0-flash"], "temperature": 0.5 },
  "content_generate": { "primary": "google/gemini-2.0-flash",         "fallbacks": ["anthropic/claude-3.7-sonnet"], "temperature": 0.7, "max_tokens": 4000 },
  "writing_evaluate": { "primary": "anthropic/claude-3.7-sonnet",     "fallbacks": ["openai/gpt-4o"], "temperature": 0.2, "response_format": "json" },
  "conversation":     { "primary": "openai/gpt-4o",                   "fallbacks": ["anthropic/claude-3.7-sonnet"], "temperature": 0.6, "stream": true },
  "quiz_generate":    { "primary": "openai/gpt-4o-mini",              "fallbacks": ["google/gemini-2.0-flash"], "temperature": 0.4, "response_format": "json" },
  "embedding":        { "primary": "openai/text-embedding-3-small",   "fallbacks": ["baai/bge-m3"], "dimensions": 1536 },
  "speech_to_text":   { "primary": "openai/whisper-1" },
  "vision_ocr":       { "primary": "google/gemini-2.0-flash",         "fallbacks": ["openai/gpt-4o"] }
}
```

> Model ids above are **OpenRouter slugs** and are examples — verify current availability/pricing
> in the OpenRouter model catalog at build time and pin what you certify. The point is: **the
> catalog changes, the app does not.**

STT/TTS: if a preferred speech model isn't on OpenRouter at build time, keep the same seam — the
router calls a `SpeechProvider` interface; the implementation can be OpenAI Whisper / a TTS vendor
directly while chat/vision/embeddings go through OpenRouter. The router API to the rest of the app
is identical either way.

### 5.3 Router contract (FastAPI)

```python
# backend/app/ai/router.py  (shape, not full impl)
class AIRequest(BaseModel):
    task_type: TaskType
    messages: list[Message] | None = None
    input_text: str | None = None
    audio_url: str | None = None
    user_id: str
    context: RagContext | None = None          # retrieved chunks for grounding
    response_schema: dict | None = None         # for structured tasks

class AIResponse(BaseModel):
    text: str | None
    json: dict | None
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    from_cache: bool

async def route(req: AIRequest) -> AIResponse:
    policy = load_route(req.task_type)          # from ai_routes (cached)
    key = cache_key(req)                         # deterministic tasks are cached in Redis
    if cached := await redis.get(key): return cached
    for model in [policy.primary, *policy.fallbacks]:
        try:
            resp = await openrouter.chat(model=model, **policy.params, messages=build(req))
            record_usage(req.user_id, req.task_type, model, resp)   # ai_usage table
            if policy.cacheable: await redis.set(key, resp, ttl=policy.ttl)
            return resp
        except (RateLimit, ModelUnavailable, Timeout):
            continue                              # try next fallback
    raise AllModelsFailed(req.task_type)
```

**Design guarantees**

- **Single egress**: only `openrouter.py` talks to the network for LLM calls.
- **Fallback chain**: any 429/5xx/timeout falls through to the next model automatically.
- **Deterministic caching**: `translate`, `vocab_example`, `quiz_generate` for identical inputs are cached in Redis (huge cost win for common words/phrases).
- **Grounding**: for `grammar_explain`, `conversation`, `quiz_generate` the router injects RAG context (§6) so answers cite curated German material, not model priors.
- **Usage accounting**: every call writes to `ai_usage` (user, task, model, tokens, cost, latency) → powers the admin cost dashboard and per-user quota enforcement.
- **Structured output**: quiz/writing tasks request JSON and are validated against a Pydantic schema; on validation failure the router retries once with a repair prompt, then falls back.

### 5.4 Voice pipeline (Speaking module)

```
mic audio ─► [speech_to_text] ─► transcript ─► [conversation w/ RAG scenario] ─► reply text
                                                        │
                                                        ▼
                                              scoring (pronunciation, grammar, fluency)
                                                        │
                                                        ▼
                                              [text_to_speech] ─► audio reply to learner
```

Scoring is a second `writing_evaluate`-style structured call over the transcript + reference
scenario; pronunciation uses STT word-confidence + a phoneme heuristic.

### 5.5 LLM tool calling (function tools)

The AI Tutor is an **agent**, not a plain chat completion: the LLM is given a set of **domain
tools** (function/tool calling) and decides which to invoke to answer. This satisfies the "≥3 tool
calls" requirement — the platform ships **six** domain-relevant tools (well above the minimum):

| Tool | Signature | What it does | Category |
|---|---|---|---|
| `search_knowledge_base` | `(query, cefr_level, skill) → chunks[]` | Retrieves grounding passages from Qdrant (RAG as a tool) | API/retrieval |
| `lookup_word` | `(lemma) → {article, plural, ipa, senses}` | German dictionary lookup — gender, plural, pronunciation | data lookup |
| `conjugate_verb` | `(verb, tense, person) → forms` | Deterministic verb conjugation (rule engine + irregular table) | calculation |
| `evaluate_writing` | `(text, target_level) → {grammar, vocab, cefr, corrections[]}` | Scores a learner's text, returns structured feedback | data analysis |
| `generate_quiz` | `(topic, cefr_level, n) → quiz JSON` | Builds a validated multiple-choice/cloze quiz | data analysis |
| `save_vocabulary` | `(user_id, lemma) → card` | Adds a word to the learner's notebook + seeds an SRS flashcard | integration (DB write) |

- **Structured & validated:** every tool has a JSON-schema signature; arguments the model produces
  are validated (Pydantic) before execution — invalid args trigger one repair attempt, then error.
- **Deterministic where it matters:** `conjugate_verb` and `lookup_word` are *not* left to the model
  — they hit a real rule engine / dictionary, so grammar facts are correct, not hallucinated.
- **Side-effect tools are authorized:** `save_vocabulary` runs under the caller's identity and RLS,
  so a tool can only write the *current* learner's rows.
- **The UI shows tool activity:** the tutor stream surfaces "🔧 called `conjugate_verb(gehen, …)`"
  chips and renders each tool's result inline (quiz cards, correction diffs, a saved-word toast) —
  this satisfies the "display tool call results" UI requirement.

### 5.6 Orchestration: LangChain over OpenRouter

The backend uses **LangChain** as the orchestration framework, with **OpenRouter** as the
OpenAI-compatible model gateway — exactly the mandated stack:

```python
from langchain_openai import ChatOpenAI          # OpenAI-compatible → points at OpenRouter
from langchain.agents import create_tool_calling_agent, AgentExecutor

llm = ChatOpenAI(
    model=route.primary,                           # model chosen per task by the AI Router (§5.2)
    base_url="https://openrouter.ai/api/v1",       # OpenRouter, OpenAI-compatible
    api_key=settings.OPENROUTER_API_KEY,
    temperature=route.temperature, streaming=True,
)
agent = create_tool_calling_agent(llm, TOOLS, TUTOR_PROMPT)   # §5.5 tools + domain prompt
executor = AgentExecutor(agent=agent, tools=TOOLS, handle_parsing_errors=True)
```

- **Model switching = swapping the `model=` string** on a LangChain `ChatOpenAI` bound to
  OpenRouter — so multi-model support (a *medium* optional task) is intrinsic, not bolted on.
- LangChain pieces used: `ChatOpenAI` (LLM), **tool-calling agent** (§5.5), **retriever** wrapping
  Qdrant for RAG (§6), **output parsers** (structured quiz/writing JSON), and **memory** backed by
  the `conversation_history` table.
- `handle_parsing_errors=True` plus the router's fallback chain (§5.3) give the required
  **error handling**; Pydantic arg-validation (§5.5) gives the required **input validation**.

> JS track note: if the whole stack must be Next.js-only, `langchain` (JS) + the same OpenRouter
> base URL is a drop-in equivalent; the Python/FastAPI split just lets LangChain-Python (the
> reference implementation) own the agent while Next.js owns the UI.

---

## 6. RAG pipeline

RAG grounds tutoring, grammar, and search in a **curated German corpus** (grammar references,
graded stories, dialogues, culture notes) plus the learner's own notes.

### 6.1 Ingestion (background worker on Render)

```
Source — either an UPLOADED FILE (PDF / DOCX / EPUB / Markdown / HTML / TXT)
         or a RESOURCE LINK (web article URL / YouTube / RSS / audio transcript)
   │
   ▼  file → Supabase Storage ;  link → fetched by worker   → enqueue job in Redis
Document Parser  (unstructured / pypdf / python-docx / ebooklib / readability / transcript)
   │
   ▼
Chunker  (structure-aware: headings/paragraphs; ~500–800 tokens, 15% overlap)
   │
   ▼
Metadata tagging  (cefr_level, skill, topic, source_id, lang)
   │
   ▼
Embed  (AI Router: task=embedding → OpenRouter)  →  vectors
   │
   ▼
Upsert into vector store collection  (+ payload)  ;  update doc row status='ready'
   → shared corpus: grammar_documents / stories / lesson_content  (admin-curated, read by all)
```

### 6.2 Retrieval (request path)

```
query ─► embed(query) ─► Qdrant search (top-k, filtered by cefr_level/skill/collection)
      ─► rerank (optional, small model) ─► assemble context window
      ─► AI Router (grounded task) ─► answer (+ cited source_ids)
```

- **Filtered search**: retrieval is scoped by the learner's CEFR level and the active module so an A1 learner isn't shown C1 material.
- **Citations**: responses carry `source_ids`; the UI can link back to the originating lesson/story.
- **Personal RAG**: the learner's notes and saved vocab live in a per-user Qdrant collection so "search my notes" and "quiz me on what I saved" work.

### 6.3 Ingestion is ADMIN-ONLY — students only consume

**Only the admin ingests content.** Students never upload — they **learn, talk, read, take tests,
and see feedback & analysis**. All ingested material lands in the **shared curated corpus** that
every learner reads from (CEFR-filtered), so there is a single, vetted, quality-controlled library.

| Actor | Can ingest? | What they do |
|---|---|---|
| **Admin** | ✅ Uploads books/docs + registers resource links & feeds → shared corpus | Curates the whole knowledge base |
| **Student** | ❌ No uploads | Reads, chats with the tutor, takes quizzes/writing/speaking tests, sees scores & analysis |
| *Teacher / creator (Phase 2)* | ✅ *(future marketplace module only)* | Publishes packs for review → marketplace |

> The learner's **notes** and **saved vocabulary** are still per-user (they are the student's own
> learning artifacts, created inside the app — not uploaded external documents). Personal RAG over
> *those* (`user_notes`) is a learning feature and is unaffected by the admin-only ingestion rule.

### 6.4 Admin ingestion sources — files *and* resource links

Two ways in for the admin, both flowing into the identical chunk → embed → vector pipeline, both
landing in the shared corpus:

**A. File upload** (book or document)

```
1. Admin requests a signed upload URL          POST /api/v1/admin/documents   (role = admin)
   Backend validates role + file type + size → returns a Supabase Storage signed URL
2. File is uploaded directly to Storage (bucket: documents)
3. Backend inserts a documents row (status='pending') + enqueues a Redis job
4. Render background WORKER parses → chunks → tags (cefr/skill) → embeds → upserts vectors → status='ready'
```
Formats: **PDF, EPUB, DOCX, Markdown (.md), HTML, .txt** — a 400-page book becomes thousands of
overlapping chunks, each citing back to `source_id`.

**B. Resource link** (a URL, YouTube video, or RSS feed)

```
1. Admin submits a URL                          POST /api/v1/admin/documents  {source_type:'web'|'youtube'|'rss', url}
2. Worker FETCHES instead of reading Storage:
     • web article → HTTP GET → readability extraction (strip nav/ads) → clean text
     • youtube     → caption/transcript track → text (never the video/audio itself)
     • rss         → register in feed_sources; each item is fetched like a web article
3. → same chunk → embed → vector pipeline; source_url stored for citation + de-dup
```

Everything is **async on the background worker**, never on the HTTP request — a big book or a slow
page can't time out the upload call. The admin UI polls `documents.status`
(`pending → processing → ready | failed`).

### 6.5 RSS feeds — self-refreshing reading material

An admin registers a feed **once**; a **scheduled worker** (Render cron / GitHub Actions cron)
re-polls it on an interval and ingests only new items (deduped on canonical URL / content hash).
This makes the Library a *living* source — fresh graded articles appear without manual work — and
powers the "News" and "Culture" categories. All feed content is shared corpus.

### 6.6 Ingestion guardrails (mandatory for online sources)

- **Copyright / licensing.** Uploading a book the platform is licensed for is fine; scraping
  paywalled or copyrighted sites is not. Online ingestion is restricted to **licensed,
  openly-licensed, or feed-authorized** material; the worker respects `robots.txt` and rate limits.
  `TODO: legal review` on which sources the admin may ingest.
- **Untrusted content = prompt injection.** Retrieved chunks are treated as **data, never
  instructions** — wrapped as reference material; the system prompt is fixed and cannot be
  overridden by fetched text.
- **Cleaning & de-dup.** Readability extraction strips boilerplate; identical items across feeds are
  de-duplicated on content hash so the same article is never embedded twice.

---

## 7. Data model — PostgreSQL

Conventions: `id uuid pk default gen_random_uuid()`, `created_at`/`updated_at timestamptz`,
soft-delete via `deleted_at`, **RLS on every user-owned table**, prices/costs where relevant in
integer cents / micro-USD.

```sql
-- Identity (Supabase Auth owns auth.users; we mirror a profile)
profiles(
  id uuid pk references auth.users,           -- 1:1 with auth.users
  role text not null default 'student',       -- student | teacher | admin
  display_name text, avatar_url text,
  goal text, cefr_level text default 'A1',
  learning_style text, daily_goal_minutes int default 20,
  native_lang text default 'en', gloss_langs text[] default '{hi,pl}',
  onboarded_at timestamptz, created_at, updated_at
)

-- Content catalog
courses(id, title, description, cefr_level, cover_url, author_id, is_published, created_at, updated_at)
lessons(id, course_id fk, title, body_md, cefr_level, order_index, kind, created_at, updated_at)
grammar_topics(id, title, cefr_level, summary_md, rules_md, examples_jsonb, mistakes_md, order_index)
stories(id, title, body_md, cefr_level, reading_minutes, grammar_focus, audio_url, translation_md, created_at)
listening_items(id, title, audio_url, transcript_md, cefr_level, vocab_jsonb, quiz_jsonb)
speaking_scenarios(id, title, prompt_md, cefr_level, persona)

-- Vocabulary & SRS
vocabulary(id, user_id fk, lemma, article, plural, meaning, pronunciation_url,
           examples_jsonb, gloss_jsonb, source_ref, status, created_at, updated_at)
flashcards(id, user_id fk, vocabulary_id fk, algo text default 'fsrs',
           ease real, interval_days int, due_at timestamptz, reps int, lapses int, last_grade int)

-- Personal knowledge
notes(id, user_id fk, folder text, title, body_md, is_pinned bool, created_at, updated_at)
bookmarks(id, user_id fk, entity_type text, entity_id uuid, created_at)

-- Progress & assessment
progress(id, user_id fk, skill text, metric text, value real, updated_at)   -- per-skill %
activity(id, user_id fk, day date, minutes int, xp int)                     -- streaks/charts
achievements(id, user_id fk, code text, earned_at)
writing_submissions(id, user_id fk, prompt, text, scores_jsonb, feedback_md, cefr_estimate, created_at)
quiz_attempts(id, user_id fk, quiz_ref, answers_jsonb, score real, created_at)

-- AI plumbing
conversation_history(id, user_id fk, thread_id uuid, role text, content, task_type, model_used, created_at)
ai_routes(task_type text pk, primary_model text, fallbacks text[], params_jsonb, updated_by, updated_at)
ai_usage(id, user_id fk, task_type, model_used, tokens_in int, tokens_out int,
         cost_micro_usd bigint, latency_ms int, from_cache bool, created_at)

-- Knowledge base registry (admin-curated shared corpus; mirrors the vector store)
documents(id, created_by fk,                   -- the admin who ingested it
          title, source_type text,             -- pdf|epub|docx|md|html|txt|web|youtube|rss
          storage_path text,                    -- for uploaded files (null for links)
          source_url text,                      -- for web/youtube/rss (null for uploads)
          content_hash text,                    -- de-dup key
          cefr_level text, skill text,
          collection text,                       -- target vector collection
          status text default 'pending',         -- pending|processing|ready|failed
          error text, chunk_count int,
          created_at, updated_at)

-- Registered online feeds (self-refreshing shared sources, §6.5; admin-managed)
feed_sources(id, created_by fk, url, cefr_level, skill,
             poll_interval_minutes int default 1440,
             last_seen_guid text, last_polled_at timestamptz,
             is_active bool default true, created_at, updated_at)

-- Billing
subscriptions(id, user_id fk, plan text, status text, stripe_customer_id, stripe_sub_id,
              current_period_end timestamptz, created_at, updated_at)
```

### RLS sketch (representative)

```sql
alter table notes enable row level security;
create policy notes_owner on notes
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
-- Content tables are readable by all authenticated users, writable only by teacher/admin:
create policy lessons_read on lessons for select using (auth.role() = 'authenticated');
create policy lessons_write on lessons for all
  using ((auth.jwt() ->> 'role') in ('teacher','admin'));

-- Documents: the curated corpus is readable by any authenticated learner; only the
-- admin may ingest/modify. Students never write here.
alter table documents enable row level security;
create policy documents_read on documents for select
  using (auth.role() = 'authenticated');
create policy documents_write on documents for all
  using ((auth.jwt() ->> 'role') = 'admin');
```

A DB trigger creates a `profiles` row on `auth.users` insert so onboarding always has a row to update.

---

## 8. Vector store — Qdrant (swappable; pgvector alternative)

| Collection | Contents | Payload filters |
|---|---|---|
| `grammar_documents` | Grammar reference chunks (shared) | `cefr_level`, `topic`, `source_id` |
| `stories` | Graded story chunks (shared) | `cefr_level`, `grammar_focus` |
| `lesson_content` | Lesson bodies (shared) | `course_id`, `cefr_level` |
| `vocabulary_examples` | Example sentences (shared) | `lemma`, `cefr_level` |
| `user_notes` | Per-user notes (personal RAG over the learner's own notes) | `user_id` (mandatory filter) |

All shared collections are **admin-curated** (students never write to them). `user_notes` is the
only per-user collection, holding the learner's *own* notes — not uploaded documents.

- **Distance:** cosine. **Vector size:** matches embedding model (e.g. 1536 for `text-embedding-3-small`) — pinned per collection; changing the embedding model means a re-index migration.
- **Payload** always includes `source_id` (FK back to Postgres `documents`/content), `cefr_level`, `skill`, `lang`.
- **Isolation:** `user_notes` queries **must** filter on `user_id`; enforced in the retrieval layer and covered by a test. Vector-store API key is backend-only.

### 8.1 The store is behind a `VectorStore` seam — swap backends without touching features

All vector reads/writes go through one interface (`upsert`, `search(collection, vector, filter, k)`,
`delete`), so the engine is a config choice, not a code rewrite:

```python
class VectorStore(Protocol):
    async def upsert(self, collection: str, points: list[Point]) -> None: ...
    async def search(self, collection: str, vector: list[float],
                     flt: Filter, k: int) -> list[Hit]: ...
    async def delete(self, collection: str, source_id: str) -> None: ...

# implementations: QdrantStore (default)  |  PgVectorStore (Supabase)  |  FakeStore (tests)
```

**Free vector-DB options** (all viable; ranked for this stack):

| Backend | Free tier | Why / when |
|---|---|---|
| **Qdrant Cloud** *(default)* | 1 GB free cluster; OSS self-host free | Best pure-vector engine — fast filtered search, quantization, payload indexes. Ideal for the large shared corpus. |
| **pgvector (in Supabase)** | **Free — already in your DB** | Zero new infrastructure; **RLS applies to vectors**, so per-user `user_notes` isolation is automatic. Great up to ~hundreds of thousands of chunks. Strongest "cheapest path" option. |
| **Chroma** | Free, OSS | Local/dev friendly; weaker for prod multi-tenant. |
| **Weaviate Cloud** | Free sandbox (trial) | Good hybrid search. |
| **Zilliz / Milvus** | Free starter tier | Very scalable, heavier to operate. |
| **LanceDB** | Free, embedded | Serverless/embedded, no server to run; younger ecosystem. |

**Recommendation:** keep **Qdrant Cloud as default** for the admin-curated shared corpus, and
support **pgvector-on-Supabase** as the drop-in free alternative — its RLS-per-row isolation is a
natural fit for the per-user `user_notes` collection. Starting on pgvector alone is a legitimate way
to ship with one fewer service and add Qdrant later.

---

## 9. API surface

REST, versioned under `/api/v1`. All endpoints require a valid Supabase JWT except health.
The Next.js app can call these directly (browser → Render) or proxy through Next route handlers.

```
POST   /api/v1/auth/sync                 # first-login profile bootstrap (idempotent)
GET    /api/v1/me                         # profile + prefs
PATCH  /api/v1/me                         # onboarding + settings

GET    /api/v1/library?level=&skill=&q=   # catalog + filters
GET    /api/v1/stories?level=
GET    /api/v1/stories/{id}
GET    /api/v1/grammar?level=
GET    /api/v1/grammar/{id}

GET    /api/v1/vocab                       # learner's words
POST   /api/v1/vocab                       # save word (from reader)
PATCH  /api/v1/vocab/{id}
GET    /api/v1/flashcards/due              # SRS queue
POST   /api/v1/flashcards/{id}/grade       # Easy/Hard/Again → schedule next

GET    /api/v1/notes  · POST · PATCH · DELETE /api/v1/notes/{id}
GET    /api/v1/progress                    # per-skill %, streak, achievements
GET    /api/v1/analysis                    # feedback & analytics: writing/speaking scores, weak spots

# AI (all funnel through the AI Router)
POST   /api/v1/ai/tutor                    # {thread_id, message, lesson_ctx} → streamed reply
POST   /api/v1/ai/explain                  # {word|topic} → structured explanation
POST   /api/v1/ai/translate                # {text, target_langs}
POST   /api/v1/ai/quiz                      # {topic, level} → quiz JSON
POST   /api/v1/ai/writing                   # {prompt, text} → scores + rewrite
POST   /api/v1/ai/speaking/turn             # multipart audio → transcript + reply + scores + audio
GET    /api/v1/search?q=                     # RAG global search

# Admin / content (role-gated) — uploads land in the SHARED curated corpus
POST   /api/v1/admin/documents             # upload file or link → shared ingest job
GET    /api/v1/admin/documents             # all docs + status + owner
DELETE /api/v1/admin/documents/{id}        # remove + purge vectors
POST   /api/v1/admin/feeds  · GET · DELETE # register/refresh shared RSS feeds
GET    /api/v1/admin/ai-routes  · PUT      # edit routing policy (no deploy)
GET    /api/v1/admin/usage                 # cost/usage analytics

GET    /healthz  /readyz                     # Render health checks
```

**Streaming:** `/ai/tutor` and `/ai/speaking/turn` use SSE (or chunked) so tokens/audio stream to the UI. OpenRouter streaming passes straight through the router.

---

## 10. Auth & security (Supabase)

- **Provider:** Supabase Auth (GoTrue) — email/password + Google + GitHub OAuth + password recovery.
- **Session:** The Next.js app uses `@supabase/ssr` to keep the session in HTTP-only cookies; the browser gets a short-lived JWT for API calls.
- **Backend verification:** FastAPI verifies every `Authorization: Bearer <jwt>` against Supabase's **JWKS endpoint** (cached), extracting `sub` (user id) and `role`. No shared static secret in the browser.
- **RLS everywhere:** even if the API layer had a bug, Postgres RLS prevents cross-user reads/writes. A CI test asserts a user cannot read another user's notes/vocab.
- **Service role key** (full DB access) lives **only** on the Render backend, never shipped to the client.
- **Secrets:** OpenRouter key, Qdrant key, Supabase service key, Stripe keys — all backend env vars on Render. The frontend only ever sees the Supabase **anon** key + URL (safe by design) and the public API base URL.
- **Rate limiting:** per-user + per-IP token buckets in Redis on all `/ai/*` routes to cap abuse and cost.
- **Input hardening:** file-type/size validation on uploads; prompt-injection mitigation on RAG (retrieved content is data, never instructions); JSON-schema validation on structured AI output.

---

## 11. Storage design (Supabase Storage)

| Bucket | Contents | Access |
|---|---|---|
| `avatars` | Profile images | public read, owner write |
| `audio` | Pronunciation clips, listening tracks, TTS output | signed URLs |
| `speaking` | Learner mic recordings | private, owner-only, signed URLs, TTL cleanup |
| `documents` | Curated KB sources (PDF/EPUB/…) uploaded by the **admin only** | private, admin write |
| `note-media` | Images/audio embedded in a learner's notes | private, owner-only |

> Resource **links** (web/YouTube/RSS) are *not* stored as files — the worker fetches and extracts
> their text on ingest; only the `source_url` is kept in the `documents` row for citation & de-dup.

- Uploads go through **signed upload URLs** issued by the backend after auth + validation.
- Learner mic recordings are transient — deleted after scoring (or short TTL) to minimize PII footprint.
- Storage RLS policies mirror the ownership model.

---

## 12. Frontend architecture

**Stack:** Next.js (App Router) · React · TypeScript · TailwindCSS · shadcn/ui · React Query · Zustand.

- **App Router segments** map to areas: `(marketing)`, `(auth)`, `(app)/dashboard`, `(app)/learn/*`, `(app)/tutor`, `(app)/library`, `(app)/notes`, `(app)/progress`, `(app)/settings`, `(admin)`.
- **Data fetching:** React Query for server state (caching, mutations, optimistic updates on flashcard grading & vocab save); Zustand for ephemeral UI state (reader theme, active thread).
- **Auth:** `@supabase/ssr` client + server helpers; middleware guards `(app)` and `(admin)` segments, redirecting unauthenticated users to `/login`.
- **Streaming UI:** the tutor and speaking screens consume SSE and render tokens/audio progressively.
- **Reading Mode** is a focused client component: max-width 820px, line-height 1.8, theme switch (light/dark/sepia/large), tap-word popover that calls `/ai/translate` + `/ai/explain` and offers "Save to vocabulary".
- **Accessibility:** WCAG 2.1 AA — semantic HTML, keyboard nav, visible focus rings, alt text, ≥44px touch targets, `prefers-reduced-motion` respected.
- **Performance:** route-level code splitting; heavy modules (speaking/voice, charts) lazy-loaded; images via `next/image`; protect LCP/INP/CLS on the dashboard and reader.

---

## 13. Design system

**Typography** — display scale 48 / 36 / 30 / 24 / 20 / 18; body 16 / 14; monospace for code, grammar rules, and vocabulary tokens.

**Cards** — every module surfaces content as a consistent card (title · level badge · meta · "Continue →").

**Reading** — max-width 820px, line-height 1.8, Inter body; light / dark / sepia / large-text modes.

**Notes** — full markdown styling (headings, blockquote, code, tables, checklists).

**Vocabulary** — consistent card: word · pronunciation · meaning · example · AI explanation · bookmark.

**AI output is never a raw chat blob** — it is rendered into structured blocks: *Summary · Examples ·
Common mistakes · Quiz · Related lessons*. This is what makes it feel like a university, not ChatGPT.

**Tokens:** define primitive → semantic → component tokens as CSS variables + Tailwind theme; dark mode via `data-theme`. Charts use a single consistent categorical palette across Progress and Admin.

---

## 14. Deployment topology

```
                 ┌───────────────────────────── Vercel ─────────────────────────────┐
   GitHub push ─►│ Next.js: preview per PR + production on main; edge CDN; ISR cache │
                 └───────────────────────────────┬──────────────────────────────────┘
                                                  │ NEXT_PUBLIC_API_URL
                 ┌───────────────────────────── Render ─────────────────────────────┐
                 │ Web Service: FastAPI (Docker) — autoscaling, /healthz              │
   GitHub push ─►│ Background Worker: ingestion queue consumer                        │
                 │ Redis (Render Key-Value or Upstash): cache / rate-limit / queue    │
                 └───────┬───────────────────────┬───────────────────┬───────────────┘
                         │                        │                   │
                ┌────────▼────────┐     ┌─────────▼────────┐  ┌───────▼─────────┐
                │ Supabase        │     │ Qdrant Cloud     │  │ OpenRouter      │
                │ Postgres+Auth+  │     │ (managed vectors)│  │ (LLM gateway)   │
                │ Storage         │     └──────────────────┘  └─────────────────┘
                └─────────────────┘
```

- **Frontend → Vercel:** connect the GitHub repo; every PR gets a preview URL, `main` deploys to production. Set `NEXT_PUBLIC_*` env vars in the Vercel project.
- **Backend → Render:** a `Dockerfile` for the FastAPI service + a `render.yaml` (Infrastructure-as-Code) declaring the web service, the background worker, and the Redis instance. Health check path `/healthz`. Auto-deploy on `main` after CI passes.
- **DB migrations:** Supabase migrations (SQL in `supabase/migrations/`) applied via CI using the Supabase CLI. RLS policies are part of the migration set.
- **Regions:** pick EU regions across Supabase / Render / Qdrant / OpenRouter routing where data residency matters; keep them co-located to cut latency.

`render.yaml` (shape):

```yaml
services:
  - type: web
    name: linguaflow-api
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    healthCheckPath: /healthz
    autoDeploy: true
    envVars:
      - key: SUPABASE_URL          ; sync: false
      - key: SUPABASE_SERVICE_KEY  ; sync: false
      - key: SUPABASE_JWKS_URL     ; sync: false
      - key: OPENROUTER_API_KEY    ; sync: false
      - key: QDRANT_URL            ; sync: false
      - key: QDRANT_API_KEY        ; sync: false
      - key: REDIS_URL             ; fromService: { type: redis, name: linguaflow-redis, property: connectionString }
  - type: worker
    name: linguaflow-ingest
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    dockerCommand: python -m app.workers.ingest
  - type: redis
    name: linguaflow-redis
    ipAllowList: []
```

---

## 15. CI/CD (GitHub Actions)

Two pipelines, gated on green checks; deploys are automatic on `main`.

```
.github/workflows/
  ci.yaml         # every PR + push: lint, typecheck, test, build (frontend + backend)
  deploy.yaml     # on main: run migrations, trigger Render + let Vercel auto-deploy
```

**`ci.yaml` jobs**

- `frontend`: `pnpm install` → `pnpm lint` → `pnpm typecheck` → `pnpm build`.
- `backend`: `pip install` (or `uv`) → `ruff` → `mypy` → `pytest` (spins up Postgres + a Qdrant service container; OpenRouter mocked via recorded fixtures so CI is hermetic and free).
- `rls-test`: applies migrations to a throwaway Postgres and asserts cross-user reads fail.

**`deploy.yaml` jobs (main only, after CI passes)**

- `migrate`: `supabase db push` (or `supabase migration up`) against the project using `SUPABASE_ACCESS_TOKEN`.
- `backend-deploy`: call the **Render Deploy Hook** (or rely on Render auto-deploy on push).
- `frontend-deploy`: Vercel auto-deploys `main`; optionally a `vercel deploy --prod` step with a project token.

**Secrets** live in GitHub Actions repo secrets (Supabase token, Render deploy hook, Vercel token, and — only for integration jobs that need it — a low-limit OpenRouter test key). No live keys in the repo.

**Hermetic AI in CI:** the OpenRouter client has a `FakeProvider` backed by recorded JSON fixtures so unit/integration tests never make a paid network call. A separate, manually-triggered `smoke` workflow hits the real OpenRouter with one tiny request to certify a model swap.

---

## 16. Environment configuration

**Frontend (Vercel)** — public unless noted:

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=            # https://linguaflow-api.onrender.com/api/v1
```

**Backend (Render)** — all secret:

```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=           # server-only, full DB access
SUPABASE_JWKS_URL=              # for JWT verification
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
QDRANT_URL=
QDRANT_API_KEY=
REDIS_URL=
STRIPE_SECRET_KEY=              # Phase 2
STRIPE_WEBHOOK_SECRET=          # Phase 2
```

Rule: **operational config that changes often (AI routes, quotas) lives in the DB and is
dashboard-editable**; only true bootstrap secrets live in env.

---

## 17. Observability, cost & rate limiting

- **Usage/cost:** every AI call writes to `ai_usage`; the admin dashboard aggregates cost per user / per task / per model / per day. Alerts fire when daily spend crosses a threshold.
- **Quotas:** Free-tier users get a monthly AI-call budget enforced in Redis + `ai_usage`; exceeding it downgrades to cheaper models or prompts an upgrade.
- **Rate limiting:** token-bucket per user and per IP on `/ai/*`.
- **Caching:** deterministic tasks (translate/vocab-example/quiz for identical inputs) cached in Redis — the single biggest cost lever for a vocabulary-heavy app.
- **Logs/metrics:** structured JSON logs from FastAPI; request-id propagation from Next → API; Render metrics + optional Sentry (errors) and a Grafana/Prometheus or Logfire target via OpenTelemetry.
- **Model health:** the router records fallbacks; a spike in fallbacks flags a degraded primary model.

---

## 18. Subscription & billing model

| Plan | Includes |
|---|---|
| **Free** | Limited AI conversations/month, basic lessons, vocabulary, flashcards |
| **Premium** | Unlimited AI tutor, voice practice, advanced stories, personalized curriculum |
| **Enterprise** | Universities & companies — seats, admin analytics, SSO |

- **Stripe** (Phase 2): products/prices for the plans, Checkout for subscribe, webhooks → `subscriptions` table. Plan gating reads `subscriptions.status` + plan caps.
- Free-tier AI limits are enforced by the quota system in §17 so the free plan can't run up an unbounded OpenRouter bill.

---

## 19. Delivery roadmap

**Phase 0 — Foundation**
- Repo scaffold (Next.js on Vercel, FastAPI on Render), Supabase project + Auth + first migrations + RLS, CI green, health checks live.

**Phase 1 — Core learning (MVP)**
- Onboarding + dashboard; Library, Stories, Reading Mode (tap-word gloss + save); Vocabulary + Flashcards (FSRS); Grammar lessons; **AI Router + OpenRouter** wired for explain/translate/quiz; Progress.

**Phase 2 — AI depth + RAG**
- Ingestion worker + Qdrant collections; grounded AI Tutor + global search; Writing evaluation; Notes with AI assist.

**Phase 3 — Voice + monetization**
- Speaking module (STT→LLM→TTS + scoring); Listening; Stripe subscriptions + plan gating + quotas; admin cost dashboard + AI-route editor.

**Phase 4 — Ecosystem**
- Teacher/creator tools; Marketplace; certifications; enterprise SSO & seats.

---

## 20. Repository layout

Monorepo (pnpm workspace for JS + a Python backend package):

```
linguaflow/
├── frontend/                     # Next.js (Vercel)
│   ├── app/                       # App Router segments
│   ├── components/  lib/  stores/ hooks/
│   ├── supabase/                  # generated types, ssr client
│   └── package.json
├── backend/                      # FastAPI (Render)
│   ├── app/
│   │   ├── main.py                # app factory, routers, health
│   │   ├── api/v1/                # route modules
│   │   ├── ai/                    # router.py, langchain agent.py, tools/ (§5.5), openrouter.py, routes.json
│   │   ├── rag/                   # ingest, chunk, embed, retrieve (LangChain retriever over Qdrant)
│   │   ├── learning/              # SRS (FSRS/SM-2), scoring, recommendations
│   │   ├── db/                    # supabase/postgres access, models
│   │   ├── workers/               # ingest queue consumer
│   │   └── core/                  # auth (JWKS), config, redis, rate-limit
│   ├── tests/                     # pytest + recorded AI fixtures
│   └── Dockerfile
├── supabase/
│   ├── migrations/                # SQL incl. RLS
│   └── seed.sql
├── config/ai_routes.json          # routing policy seed
├── render.yaml
├── .github/workflows/{ci,deploy}.yaml
└── ARCHITECTURE.md                # this document
```

---

### Summary

LinguaFlow AI is a **learning platform with AI woven through it**, not a chatbot with lessons
bolted on. The architecture keeps that promise concrete:

- **Next.js on Vercel** for a fast, accessible, structured UI (dashboard-first, not chat-first).
- **FastAPI on Render** as the brain: an **AI Router** that switches models per task through a
  single **OpenRouter** egress with fallbacks, caching, and cost accounting — so the model catalog
  can change without touching the app.
- **Supabase** for Postgres (RLS from day one) + Auth + Storage as the system of record.
- **Qdrant Cloud** for RAG that grounds tutoring and search in curated, CEFR-filtered German content.
- **GitHub Actions** enforcing lint/type/test/RLS gates before automatic deploys.

That combination is what turns "another RAG chatbot" into a production-ready AI language university.

---

## Appendix A — Task requirements coverage (admin vs end-user)

This maps the assignment's requirements to the architecture, states whether each is **covered** or
was a **gap now filled**, points to the section, and marks whose surface it lives on:
**A = Admin**, **U = End-user (student)**, **S = System/backend**.

> Scale note: the full document describes the production platform; the graded assignment is a
> **focused slice** of it. The "MVP slice" column names the minimum needed to demo the requirement.

### A.1 Core requirements (all mandatory)

| # | Requirement | Status | Where | Side | MVP slice to demo |
|---|---|---|---|---|---|
| 1 | **RAG** — domain KB, embeddings, chunking, similarity search | ✅ Covered | §6, §8 | **A** ingests · **U** queries · **S** pipeline | Admin uploads a few German docs → chunk/embed to Qdrant → tutor retrieves |
| 2 | **Tool calling** — ≥3 domain tools | ✅ Gap filled | §5.5 | **U** triggers via tutor · **S** executes | Ship `search_knowledge_base`, `conjugate_verb`, `evaluate_writing` (3 of the 6) |
| 3 | **Domain specialisation** — focused KB, domain prompts, security | ✅ Covered | §1, §6, §10, A.4 | **A** curates · **S** prompts/security | German-learning system prompt + CEFR-tagged KB |
| 4 | **LangChain + OpenRouter, error handling, input validation** | ✅ Gap filled | §5.6, §5.3, §5.5 | **S** | `ChatOpenAI(base_url=OpenRouter)` + tool-calling agent; Pydantic validation; fallback chain |
| 5 | **UI** — intuitive, show context/sources, tool results, progress | ✅ Covered | §3, §5.5, §12 | **U** (+ **A** console) | Next.js tutor: streamed answer, source citations, tool-result chips, ingest/stream spinners |

**The only two real gaps were #2 and the explicit #4 LangChain layer — both are now in §5.5 / §5.6.**

### A.2 Optional tasks — verified status

All statuses below were confirmed by running the code against live APIs, not by inspection.

### Easy — 4 of 4 ✅
| Task | Status |
|---|---|
| Conversation history + export | ✅ history persisted; **JSON / CSV / MD / PDF** |
| Source citations | ✅ `sources-list.tsx`, live-verified |
| Interactive help / chatbot guide | ✅ the AI tutor itself |
| RAG process visualisation | ✅ retrieved passages + scores + strategy chip |

### Medium — 9 of 10 ✅
| Task | Status |
|---|---|
| **Multi-model support** | ✅ AI Router, 11 tasks, admin-editable, switching verified live |
| **Real-time KB updates** | ✅ scheduled RSS polling (`app/workers/scheduler.py`) — 41 live articles ingested |
| **Prompt-injection protection** | ✅ fenced + scrubbed passages *and* titles; speech fenced too |
| **Auth + personalisation** | ✅ JWT, onboarding, CEFR-calibrated answers |
| **Token usage & cost** | ✅ `ai_usage` + chat footer + `/admin/usage` |
| **Tool-call result visualisation** | ✅ tool chips + per-tool result cards |
| **Export in various formats** | ✅ JSON / CSV / MD / **PDF** (umlauts verified via extraction) |
| **Remote MCP server** | ✅ MCP client adapts external servers' tools into LangChain tools |
| **Rate limiting + key management** | ✅ Redis token buckets + monthly quotas |
| **Logging & monitoring** | ✅ structlog, request-ID tracing, JSON in prod |

### Hard — 6 of 7 ✅
| Task | Status |
|---|---|
| **Hybrid search** | ✅ dense + BM25 with Reciprocal Rank Fusion |
| **A/B testing RAG strategies** | ✅ stable per-user bucketing, `rag_events`, admin start/stop/results |
| **Automated KB updates** | ✅ scheduler with due-only polling + Redis single-runner lock |
| **Advanced analytics dashboard** | ✅ learner `/analysis` + admin usage/cost |
| **Tools as MCP servers** | ✅ two stdio MCP servers, verified over the real protocol |
| **RAG evaluation** | ✅ own harness — nDCG/MRR/precision/recall + LLM-judged faithfulness |
| Multi-language support | ◐ multilingual gloss; no UI i18n |

**Note on RAGAs.** The `ragas` package is **unusable** on this stack: v0.4.3 imports
`langchain_community.chat_models.vertexai`, removed in LangChain 1.x. Verified, then
uninstalled. The task permits "RAGAs **or otherwise**", so `app/eval/` implements the
standard metrics directly. The judge was tested for discrimination — grounded 1.0,
hallucinated 0.0, off-topic 0.0, honest refusal 1.0 — so its scores mean something.

**Bonus target (2 medium + 1 hard):** comfortably exceeded — e.g. *Multi-model support* +
*Prompt-injection protection* (medium) and *Automated KB updates* or *Advanced analytics* (hard)
are all already in the architecture. RAGAs eval is the cleanest extra hard task to add for polish.

### A.3 Feature split — who does what

**Admin-side (Admin console / Knowledge Base)** — §3 admin screens, §6.3–6.6, §9 `/admin/*`:
- Ingest the knowledge base: upload books/docs (PDF/EPUB/DOCX/MD/HTML/TXT) **and** link resources (web article / YouTube / RSS), tag CEFR + skill, monitor ingest jobs, purge documents.
- Register & manage auto-refreshing RSS feeds (real-time KB updates).
- Edit the **AI routing policy** (which model per task) with no redeploy — the multi-model control surface.
- View **token usage & cost** analytics across users/models, and system logs/monitoring.
- User management & content moderation.

**End-user-side (Student app)** — §3 core/personal screens, §9 non-admin routes:
- Learn: dashboard, library, stories, Reading Mode, grammar, vocabulary, flashcards, listening.
- **Talk**: AI Tutor chat + Speaking role-play (voice) — the agent that calls the §5.5 tools.
- **Read**: Kindle-style reader with tap-word gloss, audio, citations.
- **Take tests**: quizzes, writing evaluation, speaking scoring.
- **See feedback & analysis**: per-skill mastery, CEFR trend, weak-spot breakdown, streaks (§ Feedback & Analysis screen, `GET /api/v1/analysis`).
- Personal knowledge: notes (+ personal RAG over own notes), saved vocabulary, bookmarks.
- See **their own** token usage vs plan quota; export conversation history.
- **Students never ingest content** — consume-only, per the admin-only ingestion rule.

### A.4 Security & guardrails (domain-specific measures — requirement #3)

| Concern | Measure | Where |
|---|---|---|
| **Prompt injection** (esp. from ingested web/RSS) | Retrieved chunks are wrapped as **data, never instructions**; fixed system prompt; the model cannot be re-instructed by fetched text; tool args are schema-validated before execution | §5.5, §6.6, §10 |
| **Input validation** | Pydantic schemas on every API body **and** on every LLM tool-call argument; file type/size validation on uploads; one bounded repair-retry then hard error | §5.5, §5.6, §10 |
| **Error handling** | Model fallback chain on 429/5xx/timeout; `handle_parsing_errors=True`; typed error responses; graceful UI error/empty states | §5.3, §5.6 |
| **Tenant/user isolation** | Postgres **RLS on every user table** + a CI test that cross-user reads fail; tools run under caller identity | §7, §10 |
| **Secrets** | OpenRouter / Qdrant / Supabase service keys are **backend-only**; browser sees only the Supabase anon key | §10, §16 |
| **Abuse / cost** | Per-user + per-IP **rate limiting** and monthly AI **quotas** in Redis; deterministic-task caching caps spend | §10, §17 |
| **Content licensing** | Admin ingestion restricted to licensed/open/feed-authorized sources; `robots.txt` respected; `TODO: legal review` marker on terms | §6.6 |
| **PII minimisation** | Learner mic recordings deleted after scoring; no personal data in URLs | §11 |

### A.5 Reflection — known limitations & improvement ideas (evaluation criterion)

- **Hallucinated grammar** is the top domain risk → mitigated by deterministic `conjugate_verb` /
  `lookup_word` tools instead of trusting the model; next step is a **RAGAs** faithfulness eval in CI.
- **Retrieval quality** on a small KB can be thin → add **hybrid (dense + BM25) search** and a
  reranker (the *hard* optional task) and cite sources so learners can verify.
- **Cost drift** at scale → already instrumented (`ai_usage`), improvable with aggressive caching and
  cheaper models for `translate`/`vocab_example` via the routing policy.
- **Cold-start personalisation** → onboarding CEFR self-select is coarse; a short adaptive placement
  quiz would calibrate the starting level better.
- **Single-region latency** → co-locate Supabase/Render/Qdrant in one EU region; edge-cache public pages.
