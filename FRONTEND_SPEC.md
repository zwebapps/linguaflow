# Frontend Development Spec — V1 (build this in Cursor)

**You build:** `frontend/` — Next.js app.
**I build:** `backend/` — FastAPI + LangChain + local Postgres/Qdrant.
**Shared contract:** [`API_CONTRACT.md`](API_CONTRACT.md) — *never guess a shape, read it there.*

V1 deliberately **defers**: subscriptions/billing, voice/speaking, marketplace, listening,
teacher role. Those are V2+. Everything below is V1.

---

## 0. Setup

```bash
cd frontend
pnpm create next-app@latest . --ts --tailwind --app --eslint --src-dir --use-pnpm
pnpm add @tanstack/react-query zustand zod lucide-react recharts react-markdown clsx tailwind-merge date-fns
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add button card input textarea select badge tabs dialog dropdown-menu progress skeleton toast table separator avatar scroll-area sheet
```

`frontend/.env.local`
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

> The backend runs on `:8000` with CORS open to `http://localhost:3000`. Start it with
> `cd backend && docker compose up -d && uvicorn app.main:app --reload`.

---

## 1. Ground rules

1. **Contract-first.** Every request/response comes from `API_CONTRACT.md`. Mirror the types in `src/lib/types.ts` (or generate with `zod`).
2. **Every async action shows progress.** Skeletons for loads, spinners for actions, the SSE `status` event for chat, polling for ingest. This is a *graded* requirement.
3. **Every AI answer shows its sources.** Citations are a graded requirement — never hide them.
4. **Every tool call is visible.** Render tool chips + result cards. Also graded.
5. **Show token/cost.** Chat footer + analysis page.
6. **Errors are human.** Render `error.message` in an inline alert with a retry. Never a raw stack or blank screen.
7. **Validate before submitting** (zod, mirroring §11 of the contract) — instant feedback, but the server is authoritative.
8. **Accessible:** semantic HTML, keyboard reachable, visible focus rings, `aria-live` on the streaming answer, ≥44px touch targets, WCAG AA contrast.

---

## 2. Design direction

German-learning product — warm, editorial, calm. **Not** a generic AI-purple SaaS template.

```css
/* src/app/globals.css — @theme tokens */
--color-bg:        #FAF8F5;   /* warm paper */
--color-surface:   #FFFFFF;
--color-ink:       #1C1917;   /* near-black text */
--color-muted:     #6B625B;
--color-accent:    #B4451F;   /* terracotta — primary actions */
--color-accent-2:  #1E3A5F;   /* deep blue — links, info */
--color-border:    #E7E1D9;
--color-ok:        #2F6B4F;
--color-warn:      #B98900;
--color-err:       #A32E2E;
/* dark mode: ink #F5F2EE on bg #191714, same accents lightened ~12% */
```

- **Display font:** a serif (Fraunces / Source Serif) for page titles + reading content.
- **Body:** Inter / Geist.
- **Mono:** JetBrains Mono for conjugation tables, grammar rules, tool args.
- **Reading Mode:** max-width `72ch`, line-height `1.8`, font-size `19px`, themes light/dark/sepia.
- Cards: `1px` border, `radius 12px`, shadow only on hover. No heavy gradients.
- No green as a primary accent (reserve it for "correct" states only).

---

## 3. Routes

```
src/app/
├─ (auth)/login/page.tsx           · (auth)/register/page.tsx
├─ onboarding/page.tsx             4-step wizard
├─ (app)/layout.tsx                sidebar shell + auth guard
│  ├─ dashboard/page.tsx
│  ├─ tutor/page.tsx               ★ core screen
│  ├─ tutor/[threadId]/page.tsx
│  ├─ library/page.tsx             · library/[id]/page.tsx  (Reading Mode)
│  ├─ vocabulary/page.tsx
│  ├─ flashcards/page.tsx
│  ├─ quiz/page.tsx
│  ├─ writing/page.tsx
│  ├─ search/page.tsx
│  ├─ analysis/page.tsx
│  └─ settings/page.tsx
└─ (admin)/admin/layout.tsx        role guard → 404 if not admin
   ├─ admin/knowledge-base/page.tsx  ★ ingestion
   ├─ admin/models/page.tsx          AI route editor
   ├─ admin/feeds/page.tsx
   └─ admin/usage/page.tsx
```

---

## 4. Build order (ship in this sequence)

### Slice 1 — Shell + auth *(foundation)*
- [ ] `src/lib/api.ts` — typed fetch wrapper: injects `Authorization`, parses the error envelope into a thrown `ApiError`, handles 401 → redirect `/login`.
- [ ] `src/lib/types.ts` — types for every contract shape.
- [ ] Auth store (Zustand, token in `localStorage`) + React Query provider.
- [ ] `/login`, `/register` — zod-validated forms, inline field errors, submit spinner.
- [ ] `(app)/layout.tsx` — sidebar (Home · Tutor · Library · Vocabulary · Flashcards · Quiz · Writing · Analysis · Settings; Admin section only when `role==='admin'`), topbar with user menu, mobile drawer.
- [ ] `/onboarding` — 4 steps (goal · CEFR · style · daily minutes) → `PATCH /me`, progress bar across steps.

**Done when:** register → onboarding → land on dashboard; refresh keeps you logged in; logout works.

---

### Slice 2 — ★ AI Tutor (the graded centrepiece)

`POST /api/v1/chat` is **SSE over fetch** (not `EventSource` — you need POST + auth header).

```ts
// src/lib/chat-stream.ts
export async function streamChat(body: ChatRequest, on: {
  onStart(d): void; onStatus(d): void; onToolCall(d): void; onToolResult(d): void;
  onSources(d): void; onToken(d): void; onUsage(d): void; onDone(d): void; onError(d): void;
}, signal?: AbortSignal) {
  const res = await fetch(`${API}/chat`, {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    // Normalise CRLF: the server emits spec-compliant \r\n line endings, so
    // splitting on '\n\n' alone never finds a frame boundary.
    buf += value.replace(/\r\n/g, '\n');
    const frames = buf.split('\n\n'); buf = frames.pop() ?? '';
    for (const frame of frames) {
      const ev = frame.match(/^event:\s*(.+)$/m)?.[1];
      const raw = frame.match(/^data:\s*([\s\S]+)$/m)?.[1];
      if (!ev || !raw) continue;
      const d = JSON.parse(raw);
      ({ start: on.onStart, status: on.onStatus, tool_call: on.onToolCall,
         tool_result: on.onToolResult, sources: on.onSources, token: on.onToken,
         usage: on.onUsage, done: on.onDone, error: on.onError }[ev])?.(d);
    }
  }
}
```

Components to build:
- [ ] `ChatComposer` — textarea (Enter sends, Shift+Enter newline), 1–4000 char counter, disabled while streaming, **Stop** button (`AbortController`).
- [ ] `MessageBubble` — user vs assistant; assistant renders markdown (`react-markdown`); `aria-live="polite"` on the streaming node.
- [ ] `StatusIndicator` — shows the `status` event label with a spinner: *"Searching knowledge base…" / "Thinking…" / "Calling conjugate_verb…" / "Writing…"*. **This is the progress-indicator requirement.**
- [ ] `ToolChip` — `🔧 conjugate_verb` pill; pending = pulsing, done = ✓ + duration; click expands args + raw result JSON.
- [ ] `ToolResultCard` — **render per tool, don't just dump JSON:**
  - `conjugate_verb` → mono table of the 6 persons
  - `lookup_word` → word card (article · plural · IPA · meanings · examples)
  - `generate_quiz` → inline answerable quiz card
  - `evaluate_writing` → score bars + correction diffs
  - `save_vocabulary` → success toast "Added *der Tisch* to your vocabulary"
  - `search_knowledge_base` → collapsed "N passages retrieved" → expands to snippets
- [ ] `SourcesList` — numbered citations (title · snippet · score badge · link to `/library/{document_id}`). Collapsible, **open by default**.
- [ ] `UsageFooter` — `model · 1,204 in / 310 out · $0.004812 · 2.2s` (+ ⚡ badge if `from_cache`).
- [ ] `ThreadSidebar` — thread list, new chat, delete, **Export ▾** (JSON/CSV/MD → `GET …/export?format=`).
- [ ] Suggested-prompt chips on an empty thread ("Explain the dative case", "Quiz me on A2 verbs", "Conjugate *gehen*").

**Done when:** you ask a grammar question and see — status stages → tool chips filling in → sources → streaming answer → cost footer. Reload the thread and it all persists.

---

### Slice 3 — Library + Reading Mode
- [ ] `/library` — filter bar (CEFR pills · skill select · search), responsive card grid, skeletons, empty state ("No content yet — ask an admin to add material").
- [ ] `/library/[id]` — Reading Mode: `72ch` column, theme switcher (light/sepia/dark) + font-size stepper persisted to `localStorage`.
- [ ] **Tap-a-word** → `POST /tools/lookup-word` → popover with meaning, IPA, 🔊 audio, examples, **Save to vocabulary** (`POST /vocab` → toast), **Ask AI** (deep-links to `/tutor` prefilled with the word + `document_id` context).
- [ ] Word popover shows a small spinner while the lookup is in flight.

---

### Slice 4 — Vocabulary + Flashcards
- [ ] `/vocabulary` — table/grid, status tabs (All · New · Learning · Mastered), counts, delete, search.
- [ ] `/flashcards` — `GET /flashcards/due`; card flip (front `lemma` → back meaning + example + IPA + audio); 4 grade buttons (Again/Hard/Good/Easy) → `POST /flashcards/{id}/grade`; progress bar `x of n`; keyboard `Space` flip, `1–4` grade; "All caught up 🎉" empty state.

---

### Slice 5 — Tests (quiz + writing)
- [ ] `/quiz` — topic input + CEFR select + count → `POST /quiz/generate` (button shows "Generating…" spinner); render MCQ radios / cloze inputs; submit → `POST /quiz/submit`; result view: score ring, per-question ✓/✗ with `expected` + `explanation`, sources used, "Retry" + "Ask the tutor about my mistakes" (deep-link to `/tutor`).
- [ ] `/writing` — prompt + textarea (char counter, 1–5000) → `POST /writing/evaluate`; **skeleton while evaluating** (it's slow); results: 4 score bars, CEFR badge, corrections list (original → suggestion, colour-coded by `severity`), improved version in a diff-ish panel, suggestions, usage footer.

---

### Slice 5b — ★ Speaking (live voice practice)

Backend is done and tested. See **API_CONTRACT.md §12** — SSE again, but `multipart/form-data`.

- [ ] `/speaking` — scenario picker from `GET /speaking/scenarios`; show the `opening` line to start.
- [ ] **Record** with `MediaRecorder` (`audio/webm` is accepted as-is). Big push-to-talk button: idle → recording (with a level meter or timer) → sending. Ask for mic permission on first use and handle refusal with a clear message.
- [ ] Send as `FormData` (`audio`, `scenario`, `thread_id`, `cefr_level`, `want_audio`) and parse the SSE stream exactly like the tutor.
- [ ] Render, in order: your transcript → the tutor's streaming reply → the score panel → speak the reply.
- [ ] **Speaking the reply — handle BOTH `audio` event shapes** (API_CONTRACT §12). Server-side TTS is blocked on this account, so `use_browser_tts: true` is the normal path: build a `SpeechSynthesisUtterance`, set `lang = "de-DE"`, prefer a German voice from `getVoices()` (they load async — listen for `voiceschanged`), and `speechSynthesis.speak(...)`. If `data_uri` is present instead, `new Audio(data_uri).play()`. Both branches are required so nothing changes if the account later gains audio output.
- [ ] **Score panel:** grammar / fluency bars, corrections list (original → suggestion → why), and `notes`. Render **`pronunciation` visually distinct and labelled "approximate guidance"** — `pronunciation_is_approximate` is always `true` in V1 and must not look like a hard grade.
- [ ] Handle `audio.data_uri === null` (TTS failed) — keep the text reply, hide the player.
- [ ] Autoplay caveat: browsers block autoplay until a user gesture. The user pressed record, which counts — but keep a visible play button as a fallback.

### Slice 6 — Dashboard, Analysis, Search, Settings
- [ ] `/dashboard` — greeting, CEFR badge, daily-goal ring, stat cards (vocab · quizzes · streak), "Continue learning" card, recommended weak-spot card, one "Ask the tutor" card. Data from `GET /analysis`.
- [ ] `/analysis` — per-skill bars, activity chart (Recharts, last 30 days), CEFR trend line, **weak-spots table** with recommendations, **token/cost panel** (total + by-model + quota progress bar).
- [ ] `/search` — `POST /tools/search`; result list with score badges + `strategy` chip (dense/hybrid); each result links into the library.
- [ ] `/settings` — profile + learning prefs (`PATCH /me`), reading theme, logout.

---

### Slice 7 — ★ Admin
- [ ] `/admin/knowledge-base`
  - **Upload:** drag-and-drop zone (pdf/epub/docx/md/html/txt, ≤25 MB) with client-side type/size validation → `POST /admin/documents` (multipart) with an **upload % progress bar**.
  - **Add link:** URL input + type select (web/youtube/rss) → `POST /admin/documents/link`.
  - Optional CEFR + skill tagging on both.
  - **Documents table:** title · type · CEFR · chunks · **status badge** · actions (reingest / delete-with-confirm). **Poll every 2 s while any row is `pending|processing`**; animate the status badge; show `error` text on failed rows.
- [ ] `/admin/models` — **AI route editor**: table of `task_type` → primary model (searchable select from `GET /admin/models`, showing context length + $/1k) + fallback chips (reorderable) + params (temperature, max_tokens) → `PUT /admin/ai-routes/{task_type}`. Toast on save. *This is the multi-model bonus made visible.*
- [ ] `/admin/feeds` — list/add/delete RSS feeds, show `last_polled_at` + `items_ingested`.
- [ ] `/admin/usage` — date range + `group_by` toggle (day/model/task/user), totals row (cost · tokens · calls · cache-hit rate), Recharts bar/line.
- [ ] `(admin)/layout.tsx` — if `role !== 'admin'` → `notFound()`.

---

## 5. Component inventory

```
src/components/
├─ chat/       ChatComposer · MessageBubble · StatusIndicator · ToolChip
│              ToolResultCard · SourcesList · UsageFooter · ThreadSidebar
├─ reader/     ReaderShell · WordPopover · ThemeSwitcher
├─ learn/      FlashcardDeck · QuizRunner · QuizResult · WritingEvaluator · ScoreBar
├─ admin/      UploadDropzone · LinkForm · DocumentsTable · StatusBadge
│              ModelRouteEditor · UsageChart
└─ ui/         (shadcn) + StatCard · EmptyState · ErrorAlert · CefrBadge · Spinner
```

---

## 6. Error & loading states (checklist per screen)

| State | Requirement |
|---|---|
| Loading (first paint) | Skeleton matching final layout — never a bare spinner on a blank page |
| Loading (action) | Button → spinner + disabled, label changes ("Generating…") |
| Long op (ingest, writing eval, chat) | Explicit progress: % bar, polled status, or SSE `status` label |
| Empty | Illustration/icon + one sentence + a primary action |
| Error | `ErrorAlert` with `error.message` + **Retry**; 429 shows the `Retry-After` countdown |
| Offline / backend down | Banner "Can't reach the server — retrying…" |
| Forbidden (admin) | `notFound()` |

---

## 7. Definition of done for V1

- [ ] Register → onboard → chat with the tutor and get a grounded German answer
- [ ] The answer shows **sources**, **tool chips with rendered results**, **status progress**, **token cost**
- [ ] Admin uploads a PDF + adds a URL; both reach `ready` and become retrievable in chat
- [ ] Quiz + writing evaluation return scores and per-item feedback
- [ ] Vocabulary saves from the reader; flashcards schedule and grade
- [ ] Analysis shows skills, weak spots, and cost
- [ ] Admin can change the model for a task and the next chat uses it (visible in the chat model badge)
- [ ] Conversation exports as JSON/CSV/MD
- [ ] `pnpm build` + `pnpm lint` clean, no console errors, keyboard-navigable, dark mode works

---

## 8. Notes for Cursor

- Point Cursor at **`API_CONTRACT.md`** as context for anything network-related.
- Build slices in order; each slice should compile and be clickable before starting the next.
- Until my backend endpoints land, develop against **MSW mocks** shaped exactly like the contract (including a fake SSE stream) — then flip to the real API by removing the mock worker. That keeps us decoupled.
- Ask me to change the **contract** rather than working around a shape you don't like.
