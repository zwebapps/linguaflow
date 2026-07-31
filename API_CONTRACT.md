# LinguaFlow AI — API Contract (V1)

**Shared source of truth for frontend (Cursor) + backend (FastAPI).**
If a change is needed, change it *here first*, then both sides.

- Base URL (local): `http://localhost:8000`
- All paths prefixed `/api/v1`
- All request/response bodies are JSON unless stated (uploads = `multipart/form-data`)
- Auth: `Authorization: Bearer <jwt>` on every route except `/auth/*` and `/healthz`

---

## 0. Conventions

### Error shape (every 4xx/5xx)

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable message safe to display",
    "details": [{ "field": "text", "issue": "must be 1..5000 chars" }],
    "request_id": "req_01H..."
  }
}
```

Codes: `validation_error` (422) · `unauthorized` (401) · `forbidden` (403) ·
`not_found` (404) · `rate_limited` (429) · `upstream_error` (502) ·
`all_models_failed` (503) · `internal_error` (500)

> **Frontend rule:** always render `error.message`. Never dump raw JSON to the user.

### Pagination

Query: `?limit=20&cursor=<opaque>` → response `{ "items": [...], "next_cursor": "..." | null }`

### Timestamps
ISO-8601 UTC strings, e.g. `"2026-07-30T12:34:56Z"`.

### Money & tokens
Costs are returned as `cost_usd` (float, 6 dp) **and** `cost_micro_usd` (int) — display the float.

---

## 1. Auth

> V1 uses local email+password → JWT (HS256). V2 swaps to Supabase Auth; the
> `Authorization: Bearer` header contract does **not** change.

### `POST /api/v1/auth/register`
```json
// request
{ "email": "a@b.com", "password": "min8chars", "display_name": "Alex" }
// 201
{ "access_token": "eyJ...", "token_type": "bearer", "user": { "id": "uuid", "email": "a@b.com", "display_name": "Alex", "role": "student", "cefr_level": "A1", "onboarded": false } }
```
409 `validation_error` if email exists.

### `POST /api/v1/auth/login`
```json
{ "email": "a@b.com", "password": "..." }   // → same 200 payload as register
```

### `GET /api/v1/me`
```json
{ "id": "uuid", "email": "...", "display_name": "Alex", "role": "student|admin",
  "cefr_level": "A2", "goal": "travel", "learning_style": "balanced",
  "daily_goal_minutes": 20, "gloss_langs": ["en","hi"],
  "native_language": "tr", "target_language": "de", "onboarded": true }
```

### `PATCH /api/v1/me`
Any subset of: `display_name, cefr_level, goal, learning_style, daily_goal_minutes,
gloss_langs, native_language, target_language`.
Returns the full updated object. `cefr_level` ∈ `A1 A2 B1 B2 C1`.

`native_language` / `target_language` are ISO-639-1 codes validated server-side:
- unknown native code → 422 listing the supported codes;
- a target that isn't fully supported yet (e.g. `es`) → 422 `"'Spanish' is not
  available yet. Currently teachable: German"`. **Render `error.message` as-is.**

Setting `native_language` changes, everywhere and immediately: tutor explanations,
writing corrections, quiz explanations, speaking feedback, and dictionary glosses
(e.g. Tisch → *masa* for `tr`). No other client work is needed.

### `GET /api/v1/languages`
The options for both pickers — **fetch this, never hardcode the lists**:
```json
{ "native":  [ { "code": "ar", "name": "Arabic" }, …20 total, sorted by name ],
  "targets": [ { "code": "de", "name": "German", "endonym": "Deutsch" } ] }
```
`targets` contains only languages the platform can actually teach; more appear here
automatically when enabled server-side.

---

## 2. AI Tutor chat (SSE stream) — **the core screen**

### `POST /api/v1/chat`

```json
// request
{
  "thread_id": "uuid | null",          // null → backend creates a new thread
  "message": "Explain the dative case",
  "context": {                          // optional grounding hints
    "document_id": "uuid | null",
    "topic": "dative | null",
    "cefr_level": "A2 | null"
  },
  "model_override": "string | null"     // optional: force a specific model
}
```

**Response: `text/event-stream`.** Named SSE events, each `data:` is one JSON object:

| Event | `data` payload | Frontend action |
|---|---|---|
| `start` | `{ "thread_id": "uuid", "message_id": "uuid", "model": "anthropic/claude-..." }` | Show model badge; lock input |
| `status` | `{ "stage": "retrieving\|thinking\|calling_tool\|generating", "label": "Searching knowledge base…" }` | **Progress indicator** |
| `tool_call` | `{ "id": "call_1", "name": "conjugate_verb", "args": { "verb": "gehen", "tense": "praesens" } }` | Render a 🔧 tool chip (pending) |
| `tool_result` | `{ "id": "call_1", "name": "conjugate_verb", "ok": true, "result": { … }, "ms": 12 }` | Fill the chip + render result card |
| `sources` | `{ "sources": [ { "id":"uuid", "document_id":"uuid", "title":"Grammatik A2", "snippet":"…", "score":0.83, "page":12, "url":null } ] }` | Citations list under the answer |
| `token` | `{ "text": "Der " }` | Append to the streaming answer |
| `usage` | `{ "model":"…", "tokens_in":1204, "tokens_out":310, "cost_usd":0.004812, "from_cache":false, "latency_ms":2210 }` | Cost/token footer |
| `done` | `{ "message_id":"uuid", "thread_id":"uuid" }` | Unlock input |
| `error` | `{ "code":"all_models_failed", "message":"…" }` | Inline error + retry button |

Event order is guaranteed: `start` → (`status`/`tool_call`/`tool_result`/`sources` interleaved) → `token`* → `usage` → `done`.
On failure an `error` event may replace anything after `start`; `done` is always last if the stream completed.

**Frontend consumption note:** use `fetch()` + `ReadableStream` (not `EventSource` — it can't send
POST bodies or an `Authorization` header). Parse `event:` / `data:` line pairs.

### `GET /api/v1/chat/threads?limit=&cursor=`
```json
{ "items": [ { "id":"uuid", "title":"Dative case", "message_count":8, "updated_at":"…" } ], "next_cursor": null }
```

### `GET /api/v1/chat/threads/{id}`
```json
{ "id":"uuid", "title":"…",
  "messages": [
    { "id":"uuid", "role":"user", "content":"…", "created_at":"…" },
    { "id":"uuid", "role":"assistant", "content":"…", "created_at":"…",
      "model":"…", "sources":[…], "tool_calls":[ {"name":"…","args":{…},"result":{…}} ],
      "usage": { "tokens_in":0,"tokens_out":0,"cost_usd":0.0 } }
  ] }
```

### `DELETE /api/v1/chat/threads/{id}` → `204`

### `GET /api/v1/chat/threads/{id}/export?format=json|csv|md`
Returns a file download (`Content-Disposition: attachment`). *(Easy bonus task.)*

---

## 3. Direct tool endpoints

The tutor calls tools autonomously, but these screens invoke them directly.

### `POST /api/v1/tools/lookup-word` — Reading Mode tap-a-word
```json
// request
{ "lemma": "gehen", "gloss_langs": ["en","hi"] }
// 200
{ "lemma":"gehen", "pos":"verb", "article":null, "plural":null,
  "ipa":"ˈɡeːən", "audio_url":"/api/v1/tts?text=gehen",
  "meanings":[{"lang":"en","text":"to go"},{"lang":"hi","text":"जाना"}],
  "examples":[{"de":"Ich gehe nach Hause.","en":"I go home."}],
  "cefr_level":"A1", "source":"dictionary|llm" }
```

### `POST /api/v1/tools/conjugate`
```json
// request
{ "verb":"gehen", "tense":"praesens" }   // tense ∈ praesens|praeteritum|perfekt|futur1|konjunktiv2|imperativ
// 200
{ "verb":"gehen", "tense":"praesens", "is_irregular":true, "auxiliary":"sein",
  "forms":{ "ich":"gehe","du":"gehst","er_sie_es":"geht","wir":"gehen","ihr":"geht","sie_Sie":"gehen" },
  "source":"rule_engine" }
```

### `POST /api/v1/tools/search` — RAG search, used by Global Search + "show me the sources"
```json
// request
{ "query":"dative prepositions", "cefr_level":"A2|null", "skill":"grammar|null", "k":6 }
// 200
{ "query":"…", "strategy":"hybrid|dense",
  "results":[ { "id":"uuid","document_id":"uuid","title":"…","snippet":"…","score":0.83,
                "dense_score":0.81,"keyword_score":0.44,"page":12,"url":null } ],
  "took_ms": 84 }
```

---

## 4. Library & Reading Mode

### `GET /api/v1/library?level=&skill=&q=&limit=&cursor=`
```json
{ "items":[ { "id":"uuid","title":"Ein Tag im Park","source_type":"pdf|epub|md|web|youtube|rss|txt",
              "cefr_level":"A1","skill":"reading","chunk_count":42,
              "reading_minutes":5,"created_at":"…" } ], "next_cursor":null }
```

### `GET /api/v1/library/{id}`
```json
{ "id":"uuid","title":"…","cefr_level":"A1","skill":"reading","source_type":"pdf",
  "source_url":null,"reading_minutes":5,
  "content_md":"# Ein Tag im Park\n\nAnna geht…",   // full text for the reader
  "chunk_count":42,"created_at":"…" }
```

---

## 5. Vocabulary & flashcards

### `GET /api/v1/vocab?status=&limit=&cursor=`
`status ∈ new|learning|mastered`
```json
{ "items":[ { "id":"uuid","lemma":"der Tisch","article":"der","plural":"die Tische",
              "meaning":"table","ipa":"tɪʃ","examples":[{"de":"…","en":"…"}],
              "status":"learning","due_at":"…","created_at":"…" } ], "next_cursor":null }
```

### `POST /api/v1/vocab`
```json
{ "lemma":"Tisch", "source_document_id":"uuid|null" }   // backend enriches via lookup_word
// 201 → the full vocab object above (idempotent per (user, lemma))
```

### `DELETE /api/v1/vocab/{id}` → `204`

### `GET /api/v1/flashcards/due?limit=20`
```json
{ "items":[ { "card_id":"uuid","vocabulary_id":"uuid","lemma":"der Tisch","meaning":"table",
              "examples":[…],"ipa":"…","reps":3,"interval_days":4 } ], "remaining": 12 }
```

### `POST /api/v1/flashcards/{card_id}/grade`
```json
{ "grade": "again|hard|good|easy" }
// 200
{ "card_id":"uuid","interval_days":6,"due_at":"…","reps":4,"status":"learning" }
```

---

## 6. Tests — quiz & writing

### `POST /api/v1/quiz/generate`
```json
// request
{ "topic":"dative case", "cefr_level":"A2", "n":5, "document_id":"uuid|null" }
// 200
{ "quiz_id":"uuid","topic":"…","cefr_level":"A2",
  "questions":[ { "id":"q1","type":"mcq|cloze","prompt":"Ich gebe ___ Kind ein Buch.",
                  "options":["der","dem","den","das"],   // null for cloze
                  "hint":null } ],
  "sources":[ { "document_id":"uuid","title":"…","snippet":"…" } ] }
```
> Correct answers are **never** sent to the client. Grading is server-side.

### `POST /api/v1/quiz/submit`
```json
// request
{ "quiz_id":"uuid", "answers":[ { "question_id":"q1", "value":"dem" } ] }
// 200
{ "quiz_id":"uuid","score":0.8,"correct":4,"total":5,
  "results":[ { "question_id":"q1","correct":true,"expected":"dem","given":"dem",
                "explanation":"Dative for the indirect object…" } ],
  "cefr_estimate":"A2" }
```

### `POST /api/v1/writing/evaluate`
```json
// request
{ "prompt":"Describe your weekend.", "text":"Ich war am Wochenende…", "target_level":"B1" }
// 200
{ "submission_id":"uuid",
  "scores":{ "grammar":0.82, "vocabulary":0.75, "coherence":0.80, "overall":0.79 },
  "cefr_estimate":"B1",
  "corrections":[ { "original":"Ich habe gegangen","suggestion":"Ich bin gegangen",
                    "explanation":"'gehen' uses 'sein' as auxiliary.","severity":"error|warning|style",
                    "offset":12,"length":17 } ],
  "improved_version":"…", "suggestions":["…"],
  "usage":{ "tokens_in":0,"tokens_out":0,"cost_usd":0.0 } }
```

---

## 7. Feedback & analysis (student-facing)

### `GET /api/v1/analysis`
```json
{ "cefr_level":"A2",
  "skills":{ "reading":0.76,"listening":0.71,"speaking":0.68,"writing":0.88,"grammar":0.82,"vocabulary":0.64 },
  "counters":{ "vocab_total":842,"vocab_mastered":500,"quizzes_taken":24,"writings_submitted":9,"streak_days":30 },
  "activity":[ { "day":"2026-07-24","minutes":22,"xp":140 } ],
  "weak_spots":[ { "topic":"dative case","accuracy":0.42,"attempts":12,
                   "recommendation":"Review Dative Case, then retry the quiz.",
                   "document_id":"uuid|null" } ],
  "cefr_trend":[ { "day":"2026-07-01","estimate":"A1" } ],
  "usage":{ "tokens_in":184203,"tokens_out":52011,"cost_usd":0.9312,
            "by_model":[ { "model":"…","cost_usd":0.51,"calls":120 } ],
            "quota":{ "limit_calls":500,"used_calls":213,"resets_at":"…" } } }
```

---

## 8. Admin (role = `admin`; 403 otherwise)

### `POST /api/v1/admin/documents` — file upload
`multipart/form-data`: `file` (PDF/EPUB/DOCX/MD/HTML/TXT, ≤ 25 MB), `title?`, `cefr_level?`, `skill?`
```json
// 202 Accepted — ingestion is async
{ "id":"uuid","title":"…","status":"pending","source_type":"pdf","created_at":"…" }
```

### `POST /api/v1/admin/documents/link` — resource link
```json
{ "url":"https://…", "source_type":"web|youtube|rss", "cefr_level":"B1|null", "skill":"reading|null", "title":"optional" }
// 202 → same shape as above
```

### `GET /api/v1/admin/documents?status=&limit=&cursor=`
```json
{ "items":[ { "id":"uuid","title":"…","source_type":"pdf","source_url":null,
              "cefr_level":"A2","skill":"grammar",
              "status":"pending|processing|ready|failed","error":null,
              "chunk_count":42,"created_at":"…","updated_at":"…" } ], "next_cursor":null }
```
> **Frontend:** poll every 2 s while any row is `pending|processing` (progress indicator).

### `DELETE /api/v1/admin/documents/{id}` → `204` (also purges vectors)

### `POST /api/v1/admin/documents/{id}/reingest` → `202`

### `GET /api/v1/admin/ai-routes`
```json
{ "routes":[ { "task_type":"grammar_explain","primary_model":"anthropic/claude-3.7-sonnet",
               "fallbacks":["openai/gpt-4o"],
               "params":{ "temperature":0.3,"max_tokens":1200 },
               "updated_at":"…" } ] }
```

### `PUT /api/v1/admin/ai-routes/{task_type}`
```json
{ "primary_model":"openai/gpt-4o", "fallbacks":["google/gemini-2.0-flash"],
  "params":{ "temperature":0.4 } }
// 200 → the updated route
```

### `GET /api/v1/admin/models`
```json
{ "models":[ { "id":"openai/gpt-4o","name":"GPT-4o","context_length":128000,
               "prompt_usd_per_1k":0.005,"completion_usd_per_1k":0.015,
               "supports_tools":true } ] }
```

### `GET /api/v1/admin/usage?from=&to=&group_by=day|model|task|user`
```json
{ "total":{ "tokens_in":0,"tokens_out":0,"cost_usd":0.0,"calls":0,"cache_hit_rate":0.31 },
  "series":[ { "key":"2026-07-29","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"calls":0 } ] }
```

### `GET /api/v1/admin/feeds` · `POST` · `DELETE /{id}`
```json
// POST
{ "url":"https://…/rss", "cefr_level":"B1", "skill":"reading", "poll_interval_minutes":1440 }
// item
{ "id":"uuid","url":"…","cefr_level":"B1","poll_interval_minutes":1440,
  "last_polled_at":"…","is_active":true,"items_ingested":37 }
```

---

## 9. Health

`GET /healthz` → `{ "status":"ok" }`
`GET /readyz` → `{ "status":"ok", "db":true, "vector_store":true, "llm":true }`

---

## 10. Rate limits

`/chat` and `/tools/*`: 30 req/min per user. On 429 the response includes:
```
Retry-After: 12
```
```json
{ "error": { "code":"rate_limited", "message":"Too many requests. Try again in 12s.", "request_id":"…" } }
```

---

## 11. Validation rules (mirror these client-side for instant feedback)

| Field | Rule |
|---|---|
| `message` (chat) | 1–4000 chars, not blank |
| `password` | ≥ 8 chars |
| `email` | valid email |
| `text` (writing) | 1–5000 chars |
| `lemma` | 1–64 chars, letters/äöüß/- only |
| `verb` | 1–48 chars |
| `n` (quiz) | 1–20 |
| `k` (search) | 1–20 |
| `cefr_level` | `A1 A2 B1 B2 C1` |
| `grade` | `again hard good easy` |
| upload `file` | ≤ 25 MB, extension ∈ pdf/epub/docx/md/html/txt |
| `url` | http(s) only, no localhost/private IPs |

Server-side validation is authoritative (Pydantic); client-side is UX only.

Voice adds: `audio` file ≤ 20 MB, container ∈ wav/mp3/mp4/m4a/webm/ogg/flac ·
`scenario` ∈ the ids from `GET /speaking/scenarios`.

---

## 12. Speaking — live voice practice (SSE)

The learner speaks, the tutor replies in German, and the turn is scored. STT, chat and
TTS all run server-side through OpenRouter, so the browser only records and plays audio.

**Push-to-talk, not full duplex.** Record a turn, send it, get a spoken reply back.

### `GET /api/v1/speaking/scenarios`
```json
[ { "id":"restaurant", "title":"Ordering food",
    "persona":"a friendly waiter in a Berlin café",
    "opening":"Guten Tag! Was möchten Sie bestellen?" } ]
```
Use `opening` to start the conversation (show it, and optionally speak it) before the
learner's first turn.

### `POST /api/v1/speaking/turn`

**`multipart/form-data`** (not JSON — it carries the recording):

| Field | Type | Notes |
|---|---|---|
| `audio` | file | the recording; ≤ 20 MB. `MediaRecorder`'s `audio/webm` is fine |
| `scenario` | string | default `smalltalk` |
| `thread_id` | uuid | omit to start a new conversation |
| `cefr_level` | string | defaults to the learner's profile level |
| `want_audio` | bool | `false` to skip TTS (faster, text only) |

**Response: `text/event-stream`.** Same parsing approach as §2 (fetch + ReadableStream).

| Event | `data` | Frontend action |
|---|---|---|
| `start` | `{ "thread_id", "scenario" }` | lock the mic button |
| `status` | `{ "stage": "transcribing\|thinking\|scoring\|speaking", "label": "…" }` | **progress indicator** |
| `transcript` | `{ "text", "model", "duration_s" }` | show what the learner said |
| `token` | `{ "text": "Gern " }` | append the tutor's reply |
| `scores` | see below | feedback panel |
| `audio` | see below — **may ask you to speak it in the browser** | play it, or call `speechSynthesis` |
| `usage` | `{ "model","stt_model","tokens_in","tokens_out","cost_usd","latency_ms" }` | cost footer |
| `done` | `{ "message_id", "thread_id" }` | unlock the mic |
| `error` | `{ "code", "message" }` | inline error + retry |

`scores` payload:
```json
{ "pronunciation": 0.84, "grammar": 0.78, "fluency": 0.81, "overall": 0.80,
  "pronunciation_is_approximate": true,
  "notes": ["Speaking pace was slow (~48 words/min)."],
  "corrections": [ { "original":"Ich habe gegangen", "suggestion":"Ich bin gegangen",
                     "explanation":"'gehen' takes 'sein' in the Perfekt." } ],
  "cefr_level": "A2" }
```

> **`pronunciation_is_approximate` is always `true` in V1** and the UI **must** reflect
> that. There is no phoneme-level aligner: the score is inferred from transcript quality.
> Label it "guidance", not a grade — don't render it identically to the grammar score.

### The `audio` event has two shapes — handle both

**Server-generated audio:**
```json
{ "data_uri": "data:audio/mpeg;base64,…", "media_type": "audio/mpeg",
  "model": "deepgram/aura-2", "use_browser_tts": false }
```

**Browser must speak it** (the common case — see the note below):
```json
{ "data_uri": null, "use_browser_tts": true,
  "text": "Guten Tag! Welchen Kuchen möchten Sie?", "lang": "de-DE" }
```

```js
if (d.use_browser_tts) {
  const u = new SpeechSynthesisUtterance(d.text);
  u.lang = d.lang;                       // "de-DE"
  speechSynthesis.speak(u);
} else if (d.data_uri) {
  new Audio(d.data_uri).play();
}
```

> **Why browser TTS is the default.** Verified against a live account: no reachable
> OpenRouter model can emit audio — every audio-output model is guardrail-blocked, and
> allowed models reject `modalities: ["audio"]`. **Speech-to-text works fine**
> server-side (a multimodal chat model transcribes German accurately), so only the
> *output* half moves to the browser. `SpeechSynthesis` is free, has `de-DE` voices, and
> keeps generated audio off third-party servers. If the account later gains audio-output
> access, the server sends `data_uri` and `use_browser_tts: false` — no frontend change
> needed, which is why you must handle both shapes.

Pick a German voice explicitly when one is available:
```js
const voice = speechSynthesis.getVoices().find(v => v.lang.startsWith('de'));
if (voice) u.voice = voice;   // voices load async — listen for 'voiceschanged'
```
