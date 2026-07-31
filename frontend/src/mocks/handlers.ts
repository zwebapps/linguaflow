import { http, HttpResponse, delay } from "msw";
import { API_BASE } from "@/lib/env";
import type {
  AuthResponse,
  ChatRequest,
  QuizGenerateResponse,
  QuizQuestion,
  QuizSubmitResponse,
  User,
  WritingEvaluateResponse,
} from "@/lib/types";
import {
  adminDocuments,
  adminFeeds,
  adminUser,
  aiRoutes,
  analysisSnapshot,
  createThread,
  demoUser,
  flashcards,
  getThread,
  libraryContent,
  libraryItems,
  nextMessageId,
  pendingQuizzes,
  quizAnswers,
  scheduleMockIngest,
  scheduleMockReingest,
  threadMessages,
  threads,
  uid,
  vocabItems,
} from "./mock-db";
import { sourceTypeFromFileName } from "@/lib/admin-ingest";
import type { AdminDocument, AdminFeed, AiRoute } from "@/lib/types";

const base = API_BASE;

function bearerUser(req: Request): User | null {
  const auth = req.headers.get("Authorization");
  if (!auth?.startsWith("Bearer ")) return null;
  const token = auth.slice(7);
  if (token.startsWith("admin-")) return { ...adminUser };
  if (token.startsWith("student-")) return { ...demoUser };
  return null;
}

function requireUser(req: Request): User {
  const u = bearerUser(req);
  if (!u) {
    return HttpResponse.json(
      { error: { code: "unauthorized", message: "Please sign in again." } },
      { status: 401 },
    ) as unknown as User;
  }
  return u;
}

function sseFrame(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

async function buildChatStream(body: ChatRequest, user: User) {
  let threadId = body.thread_id;
  if (!threadId) {
    const t = createThread(body.message.slice(0, 48));
    threadId = t.id;
  }
  const userMsgId = nextMessageId();
  const assistantId = nextMessageId();
  const now = new Date().toISOString();
  threadMessages[threadId] ??= [];
  threadMessages[threadId].push({
    id: userMsgId,
    role: "user",
    content: body.message,
    created_at: now,
  });

  const model = "anthropic/claude-3.5-sonnet";
  const answer =
    "Kurz zusammengefasst: Der **Dativ** markiert oft den indirekten Objekt oder Ort (Wo?), der **Akkusativ** das direkte Objekt oder die Richtung (Wohin?). Bei Wechselpräpositionen entscheidet Bewegung vs. Position.\n\nMöchtest du eine Mini-Übung?";

  const sources = [
    {
      id: "src-live-1",
      document_id: "doc-dativ",
      title: "Wechselpräpositionen — Kurzreferenz",
      snippet: "Akkusativ bei Richtung, Dativ bei Position.",
      score: 0.89,
      page: 1,
      url: null,
    },
  ];

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const push = (ev: string, data: unknown) => {
        controller.enqueue(encoder.encode(sseFrame(ev, data)));
      };
      push("start", { thread_id: threadId, message_id: assistantId, model });
      await delay(200);
      push("status", { stage: "retrieving", label: "Searching your library…" });
      await delay(400);
      push("tool_call", {
        id: "call_1",
        name: "conjugate_verb",
        args: { verb: "gehen", tense: "praesens" },
      });
      await delay(300);
      push("status", { stage: "calling_tool", label: "Calling conjugate_verb…" });
      push("tool_result", {
        id: "call_1",
        name: "conjugate_verb",
        ok: true,
        ms: 18,
        result: {
          verb: "gehen",
          tense: "praesens",
          is_irregular: true,
          auxiliary: "sein",
          forms: {
            ich: "gehe",
            du: "gehst",
            er_sie_es: "geht",
            wir: "gehen",
            ihr: "geht",
            sie_Sie: "gehen",
          },
          source: "rule_engine",
        },
      });
      await delay(200);
      push("sources", { sources });
      await delay(150);
      push("status", { stage: "generating", label: "Writing…" });
      for (const word of answer.split(/(\s+)/)) {
        if (!word) continue;
        push("token", { text: word });
        await delay(word.length > 4 ? 28 : 12);
      }
      push("usage", {
        model,
        tokens_in: 640,
        tokens_out: 180,
        cost_usd: 0.003812,
        from_cache: false,
        latency_ms: 2100,
      });
      push("done", { message_id: assistantId, thread_id: threadId });

      threadMessages[threadId!].push({
        id: assistantId,
        role: "assistant",
        content: answer,
        created_at: new Date().toISOString(),
        model,
        sources,
        tool_calls: [
          {
            name: "conjugate_verb",
            args: { verb: "gehen", tense: "praesens" },
            result: {
              verb: "gehen",
              forms: { ich: "gehe", du: "gehst", er_sie_es: "geht" },
            },
          },
        ],
        usage: { tokens_in: 640, tokens_out: 180, cost_usd: 0.003812 },
      });
      const summary = threads.find((t) => t.id === threadId);
      if (summary) {
        summary.message_count = threadMessages[threadId!].length;
        summary.updated_at = new Date().toISOString();
      }
      controller.close();
    },
  });

  return new HttpResponse(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

export const handlers = [
  http.post(`${base}/auth/register`, async ({ request }) => {
    const body = (await request.json()) as { email: string; display_name: string };
    if (body.email.includes("ops@") || body.email.includes("admin"))
      return HttpResponse.json(
        { error: { code: "validation_error", message: "Use the learner sign-up — not the ops portal." } },
        { status: 422 },
      );
    const res: AuthResponse = {
      access_token: `student-${Date.now()}`,
      token_type: "bearer",
      user: { ...demoUser, email: body.email, display_name: body.display_name, onboarded: false },
    };
    return HttpResponse.json(res, { status: 201 });
  }),

  http.post(`${base}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    const emailLower = body.email.toLowerCase();
    if (emailLower.includes("ops@") || emailLower.includes("admin")) {
      const res: AuthResponse = {
        access_token: `admin-${Date.now()}`,
        token_type: "bearer",
        user: { ...adminUser, email: body.email },
      };
      return HttpResponse.json(res);
    }
    const res: AuthResponse = {
      access_token: `student-${Date.now()}`,
      token_type: "bearer",
      user: { ...demoUser, email: body.email },
    };
    return HttpResponse.json(res);
  }),

  http.get(`${base}/me`, ({ request }) => {
    const u = bearerUser(request);
    if (!u)
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    return HttpResponse.json(u);
  }),

  http.patch(`${base}/me`, async ({ request }) => {
    const u = bearerUser(request);
    if (!u)
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const patch = (await request.json()) as Partial<User>;
    Object.assign(demoUser, patch, { onboarded: true });
    Object.assign(adminUser, patch, { onboarded: true });
    return HttpResponse.json({ ...u, ...patch, onboarded: true });
  }),

  http.post(`${base}/chat`, async ({ request }) => {
    const u = bearerUser(request);
    if (!u)
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as ChatRequest;
    return buildChatStream(body, u);
  }),

  http.get(`${base}/chat/threads`, ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    return HttpResponse.json({ items: threads, next_cursor: null });
  }),

  http.get(`${base}/chat/threads/:id`, ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const thread = getThread(params.id as string);
    if (!thread)
      return HttpResponse.json(
        { error: { code: "not_found", message: "Thread not found." } },
        { status: 404 },
      );
    return HttpResponse.json(thread);
  }),

  http.delete(`${base}/chat/threads/:id`, ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const id = params.id as string;
    const idx = threads.findIndex((t) => t.id === id);
    if (idx >= 0) threads.splice(idx, 1);
    delete threadMessages[id];
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${base}/chat/threads/:id/export`, ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const url = new URL(request.url);
    const format = url.searchParams.get("format") ?? "json";
    const thread = getThread(params.id as string);
    const body =
      format === "md"
        ? `# ${thread?.title ?? "Chat"}\n\n${thread?.messages.map((m) => `**${m.role}**: ${m.content}`).join("\n\n")}`
        : JSON.stringify(thread, null, 2);
    return new HttpResponse(body, {
      headers: {
        "Content-Disposition": `attachment; filename="thread-${params.id}.${format}"`,
        "Content-Type": format === "json" ? "application/json" : "text/plain",
      },
    });
  }),

  http.get(`${base}/library`, ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const url = new URL(request.url);
    const q = url.searchParams.get("q")?.toLowerCase();
    let items = libraryItems;
    if (q) items = items.filter((i) => i.title.toLowerCase().includes(q));
    return HttpResponse.json({ items, next_cursor: null });
  }),

  http.get(`${base}/library/:id`, ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const doc = libraryContent[params.id as string];
    if (!doc)
      return HttpResponse.json(
        { error: { code: "not_found", message: "Document not found." } },
        { status: 404 },
      );
    return HttpResponse.json(doc);
  }),

  http.post(`${base}/tools/lookup-word`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as { lemma: string };
    await delay(400);
    const lemma = body.lemma.replace(/^der |^die |^das /, "");
    return HttpResponse.json({
      lemma,
      pos: "verb",
      article: null,
      plural: null,
      ipa: "ˈɡeːən",
      audio_url: `/api/v1/tts?text=${encodeURIComponent(lemma)}`,
      meanings: [{ lang: "en", text: `meaning of ${lemma}` }],
      examples: [{ de: `Beispiel mit ${lemma}.`, en: "Example sentence." }],
      cefr_level: "A2",
      source: "dictionary",
    });
  }),

  http.post(`${base}/tools/search`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as { query: string };
    await delay(300);
    return HttpResponse.json({
      query: body.query,
      strategy: "hybrid",
      results: libraryItems.slice(0, 3).map((item, i) => ({
        id: `res-${i}`,
        document_id: item.id,
        title: item.title,
        snippet: `…${body.query}…`,
        score: 0.85 - i * 0.05,
        dense_score: 0.8,
        keyword_score: 0.5,
        page: 1,
        url: null,
      })),
      took_ms: 84,
    });
  }),

  http.get(`${base}/vocab`, ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    let items = vocabItems;
    if (status) items = items.filter((v) => v.status === status);
    return HttpResponse.json({ items, next_cursor: null });
  }),

  http.post(`${base}/vocab`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as { lemma: string };
    const item = {
      id: uid("vocab"),
      lemma: body.lemma.startsWith("der") ? body.lemma : `der ${body.lemma}`,
      article: "der",
      plural: null,
      meaning: "saved word",
      ipa: "—",
      examples: [],
      status: "new" as const,
      due_at: null,
      created_at: new Date().toISOString(),
    };
    vocabItems.unshift(item);
    return HttpResponse.json(item, { status: 201 });
  }),

  http.delete(`${base}/vocab/:id`, ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const idx = vocabItems.findIndex((v) => v.id === params.id);
    if (idx >= 0) vocabItems.splice(idx, 1);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${base}/flashcards/due`, ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    return HttpResponse.json({ items: flashcards, remaining: flashcards.length });
  }),

  http.post(`${base}/flashcards/:id/grade`, async ({ request, params }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    await delay(200);
    const idx = flashcards.findIndex((c) => c.card_id === params.id);
    if (idx >= 0) flashcards.splice(idx, 1);
    return HttpResponse.json({
      card_id: params.id,
      interval_days: 4,
      due_at: new Date(Date.now() + 86400000 * 4).toISOString(),
      reps: 3,
      status: "learning",
    });
  }),

  http.post(`${base}/quiz/generate`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as { topic: string; cefr_level: string; n: number };
    await delay(800);
    const quiz_id = uid("quiz");
    const quiz: QuizGenerateResponse = {
      quiz_id,
      topic: body.topic,
      cefr_level: body.cefr_level as QuizGenerateResponse["cefr_level"],
      questions: [
        {
          id: "q1",
          type: "mcq",
          prompt: "Ich gebe ___ Kind ein Buch.",
          options: ["der", "dem", "den", "das"],
          hint: null,
        },
        {
          id: "q2",
          type: "mcq",
          prompt: "Das Bild hängt ___ Wand. (an)",
          options: ["an der", "an die", "am", "ans"],
          hint: null,
        },
        {
          id: "q3",
          type: "cloze",
          prompt: "Sie setzt sich ___ Sofa. (auf)",
          options: null,
          hint: "Akkusativ — Wohin?",
        },
      ].slice(0, body.n) as QuizQuestion[],
      sources: [
        {
          document_id: "doc-dativ",
          title: "Wechselpräpositionen",
          snippet: "Dativ vs Akkusativ",
        },
      ],
    };
    pendingQuizzes[quiz_id] = quiz;
    quizAnswers[quiz_id] = { q1: "dem", q2: "an der", q3: "auf das" };
    return HttpResponse.json(quiz);
  }),

  http.post(`${base}/quiz/submit`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as {
      quiz_id: string;
      answers: { question_id: string; value: string }[];
    };
    await delay(500);
    const expected = quizAnswers[body.quiz_id] ?? {};
    const results = body.answers.map((a) => {
      const exp = expected[a.question_id] ?? "";
      return {
        question_id: a.question_id,
        correct: a.value.trim().toLowerCase() === exp.toLowerCase(),
        expected: exp,
        given: a.value,
        explanation: "Review case government for prepositions.",
      };
    });
    const correct = results.filter((r) => r.correct).length;
    const res: QuizSubmitResponse = {
      quiz_id: body.quiz_id,
      score: correct / results.length,
      correct,
      total: results.length,
      results,
      cefr_estimate: "A2",
    };
    return HttpResponse.json(res);
  }),

  http.post(`${base}/writing/evaluate`, async ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    const body = (await request.json()) as { text: string };
    await delay(1200);
    const res: WritingEvaluateResponse = {
      submission_id: uid("writing"),
      scores: { grammar: 0.82, vocabulary: 0.75, coherence: 0.8, overall: 0.79 },
      cefr_estimate: "B1",
      corrections: [
        {
          original: "Ich habe gegangen",
          suggestion: "Ich bin gegangen",
          explanation: "'gehen' uses 'sein' as auxiliary.",
          severity: "error",
          offset: 0,
          length: 17,
        },
      ],
      improved_version: body.text.replace("Ich habe gegangen", "Ich bin gegangen"),
      suggestions: ["Vary sentence openings.", "Add a temporal adverb."],
      usage: { tokens_in: 400, tokens_out: 120, cost_usd: 0.0021 },
    };
    return HttpResponse.json(res);
  }),

  http.get(`${base}/analysis`, ({ request }) => {
    if (!bearerUser(request))
      return HttpResponse.json(
        { error: { code: "unauthorized", message: "Please sign in." } },
        { status: 401 },
      );
    return HttpResponse.json(analysisSnapshot);
  }),

  http.get(`${base}/admin/documents`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({ items: [...adminDocuments], next_cursor: null });
  }),

  http.post(`${base}/admin/documents`, async ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    await delay(400);
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File))
      return HttpResponse.json(
        { error: { code: "validation_error", message: "file is required." } },
        { status: 422 },
      );
    const title =
      (typeof form.get("title") === "string" && form.get("title")) ||
      file.name.replace(/\.[^.]+$/, "");
    const id = uid("adm-doc");
    const now = new Date().toISOString();
    const doc: AdminDocument = {
      id,
      title: String(title),
      source_type: sourceTypeFromFileName(file.name),
      source_url: null,
      cefr_level: (form.get("cefr_level") as AdminDocument["cefr_level"]) || null,
      skill: (form.get("skill") as string) || null,
      status: "pending",
      error: null,
      chunk_count: 0,
      created_at: now,
      updated_at: now,
    };
    adminDocuments.unshift(doc);
    scheduleMockIngest(id);
    return HttpResponse.json(doc, { status: 202 });
  }),

  http.post(`${base}/admin/documents/link`, async ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    await delay(300);
    const body = (await request.json()) as {
      url: string;
      source_type: string;
      title?: string;
      cefr_level?: AdminDocument["cefr_level"];
      skill?: string | null;
    };
    const id = uid("adm-doc");
    const now = new Date().toISOString();
    const doc: AdminDocument = {
      id,
      title: body.title || body.url,
      source_type: body.source_type,
      source_url: body.url,
      cefr_level: body.cefr_level ?? null,
      skill: body.skill ?? null,
      status: "pending",
      error: null,
      chunk_count: 0,
      created_at: now,
      updated_at: now,
    };
    adminDocuments.unshift(doc);
    scheduleMockIngest(id);
    return HttpResponse.json(doc, { status: 202 });
  }),

  http.delete(`${base}/admin/documents/:id`, ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const idx = adminDocuments.findIndex((d) => d.id === params.id);
    if (idx >= 0) adminDocuments.splice(idx, 1);
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${base}/admin/documents/:id/reingest`, ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const doc = adminDocuments.find((d) => d.id === params.id);
    if (!doc)
      return HttpResponse.json(
        { error: { code: "not_found", message: "Document not found." } },
        { status: 404 },
      );
    scheduleMockReingest(doc.id);
    return HttpResponse.json({ status: "processing" }, { status: 202 });
  }),

  http.get(`${base}/admin/ai-routes`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({ routes: aiRoutes });
  }),

  http.put(`${base}/admin/ai-routes/:task_type`, async ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const body = (await request.json()) as {
      primary_model: string;
      fallbacks: string[];
      params: { temperature?: number; max_tokens?: number };
    };
    const idx = aiRoutes.findIndex((r) => r.task_type === params.task_type);
    if (idx < 0)
      return HttpResponse.json(
        { error: { code: "not_found", message: "Route not found." } },
        { status: 404 },
      );
    const updated: AiRoute = {
      ...aiRoutes[idx],
      primary_model: body.primary_model,
      fallbacks: body.fallbacks,
      params: body.params,
      updated_at: new Date().toISOString(),
    };
    aiRoutes[idx] = updated;
    return HttpResponse.json(updated);
  }),

  http.get(`${base}/admin/models`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({
      models: [
        {
          id: "openai/gpt-4o",
          name: "GPT-4o",
          context_length: 128000,
          prompt_usd_per_1k: 0.005,
          completion_usd_per_1k: 0.015,
          supports_tools: true,
        },
        {
          id: "anthropic/claude-3.5-sonnet",
          name: "Claude 3.5 Sonnet",
          context_length: 200000,
          prompt_usd_per_1k: 0.003,
          completion_usd_per_1k: 0.015,
          supports_tools: true,
        },
      ],
    });
  }),

  http.get(`${base}/admin/feeds`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({ items: adminFeeds });
  }),

  http.post(`${base}/admin/feeds`, async ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const body = (await request.json()) as {
      url: string;
      cefr_level: AdminFeed["cefr_level"];
      poll_interval_minutes: number;
    };
    const feed: AdminFeed = {
      id: uid("feed"),
      url: body.url,
      cefr_level: body.cefr_level,
      poll_interval_minutes: body.poll_interval_minutes,
      last_polled_at: null,
      is_active: true,
      items_ingested: 0,
    };
    adminFeeds.push(feed);
    return HttpResponse.json(feed, { status: 201 });
  }),

  http.delete(`${base}/admin/feeds/:id`, ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const idx = adminFeeds.findIndex((f) => f.id === params.id);
    if (idx >= 0) adminFeeds.splice(idx, 1);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${base}/admin/experiments`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({
      experiments: [
        {
          name: "retrieval_strategy_v1",
          enabled: false,
          arms: { hybrid: 0.5, dense: 0.5 },
          description: "Shipped default (mock).",
          updated_at: null,
        },
      ],
    });
  }),

  http.put(`${base}/admin/experiments/:name`, async ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const body = (await request.json()) as {
      enabled: boolean;
      arms: Record<string, number>;
      description?: string | null;
    };
    return HttpResponse.json({
      name: params.name,
      enabled: body.enabled,
      arms: body.arms,
      description: body.description ?? null,
      updated_at: new Date().toISOString(),
    });
  }),

  http.get(`${base}/admin/experiments/:name/results`, ({ request, params }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    return HttpResponse.json({
      experiment: params.name,
      total_events: 42,
      winner: null,
      note: "Only 42 events recorded — too few to call a winner (need 30+).",
      arms: [
        {
          arm: "hybrid",
          impressions: 22,
          mean_results: 4.2,
          mean_top_score_within_arm: 0.81,
          mean_latency_ms: 120,
          zero_result_rate: 0.05,
        },
        {
          arm: "dense",
          impressions: 20,
          mean_results: 3.8,
          mean_top_score_within_arm: 0.79,
          mean_latency_ms: 95,
          zero_result_rate: 0.08,
        },
      ],
    });
  }),

  http.get(`${base}/admin/usage`, ({ request }) => {
    const u = bearerUser(request);
    if (!u || u.role !== "admin")
      return HttpResponse.json(
        { error: { code: "forbidden", message: "Admin access required." } },
        { status: 403 },
      );
    const url = new URL(request.url);
    const groupBy = url.searchParams.get("group_by") ?? "day";
    const seriesByGroup: Record<string, { key: string; tokens_in: number; tokens_out: number; cost_usd: number; calls: number }[]> = {
      day: [
        { key: "2026-07-28", tokens_in: 20000, tokens_out: 6000, cost_usd: 0.12, calls: 30 },
        { key: "2026-07-29", tokens_in: 24000, tokens_out: 7000, cost_usd: 0.14, calls: 35 },
        { key: "2026-07-30", tokens_in: 18000, tokens_out: 5500, cost_usd: 0.11, calls: 28 },
      ],
      model: [
        { key: "gpt-4o", tokens_in: 42000, tokens_out: 12000, cost_usd: 0.28, calls: 55 },
        { key: "claude-3.5", tokens_in: 38000, tokens_out: 11000, cost_usd: 0.24, calls: 48 },
      ],
      task: [
        { key: "chat_tutor", tokens_in: 50000, tokens_out: 15000, cost_usd: 0.32, calls: 70 },
        { key: "quiz_generate", tokens_in: 12000, tokens_out: 4000, cost_usd: 0.08, calls: 18 },
      ],
      user: [
        { key: "learner@…", tokens_in: 45000, tokens_out: 13000, cost_usd: 0.29, calls: 62 },
        { key: "ops@…", tokens_in: 8000, tokens_out: 2000, cost_usd: 0.05, calls: 12 },
      ],
    };
    const series = seriesByGroup[groupBy] ?? seriesByGroup.day;
    return HttpResponse.json({
      total: {
        tokens_in: 120000,
        tokens_out: 40000,
        cost_usd: 0.62,
        calls: 180,
        cache_hit_rate: 0.31,
      },
      series,
    });
  }),

  http.get(`${base}/healthz`, () => HttpResponse.json({ status: "ok" })),
];
