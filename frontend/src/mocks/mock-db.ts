import type {
  AdminDocument,
  AdminFeed,
  AiRoute,
  AnalysisResponse,
  ChatMessage,
  ChatThread,
  ChatThreadSummary,
  FlashcardDue,
  LibraryDocument,
  LibraryItem,
  QuizGenerateResponse,
  User,
  VocabItem,
} from "@/lib/types";

export const DEMO_PASSWORD = "demo12345";

export const demoUser: User = {
  id: "user-student-1",
  email: "learner@deutschflow.ai",
  display_name: "Alex",
  role: "student",
  cefr_level: "B1",
  goal: "travel",
  learning_style: "balanced",
  daily_goal_minutes: 20,
  gloss_langs: ["en"],
  onboarded: true,
};

export const adminUser: User = {
  id: "user-admin-1",
  email: "ops@deutschflow.ai",
  display_name: "Jordan (Ops)",
  role: "admin",
  cefr_level: "C1",
  goal: "work",
  learning_style: "balanced",
  daily_goal_minutes: 0,
  gloss_langs: ["en"],
  onboarded: true,
};

export const libraryDocId = "doc-park";

export const libraryItems: LibraryItem[] = [
  {
    id: "doc-dativ",
    title: "Der Dativ",
    source_type: "md",
    cefr_level: "A2",
    skill: "grammar",
    chunk_count: 6,
    reading_minutes: 4,
    created_at: "2026-07-01T10:00:00Z",
  },
  {
    id: "doc-praesens",
    title: "Das Präsens",
    source_type: "md",
    cefr_level: "A1",
    skill: "grammar",
    chunk_count: 5,
    reading_minutes: 3,
    created_at: "2026-06-28T10:00:00Z",
  },
  {
    id: "doc-akkusativ",
    title: "Präpositionen mit Akkusativ",
    source_type: "md",
    cefr_level: "A2",
    skill: "grammar",
    chunk_count: 7,
    reading_minutes: 4,
    created_at: "2026-06-20T10:00:00Z",
  },
  {
    id: libraryDocId,
    title: "Ein Tag im Park",
    source_type: "md",
    cefr_level: "A1",
    skill: "reading",
    chunk_count: 10,
    reading_minutes: 6,
    created_at: "2026-06-15T10:00:00Z",
  },
];

export const libraryContent: Record<string, LibraryDocument> = {
  "doc-dativ": {
    ...libraryItems[0],
    source_url: null,
    content_md: `# Der Dativ

Der Dativ antwortet auf die Frage **wem?** — zum Beispiel: Ich gebe **dem** Kind ein Buch.`,
  },
  "doc-praesens": {
    ...libraryItems[1],
    source_url: null,
    content_md: `# Das Präsens

Im Präsens beschreiben wir Gegenwart und Gewohnheiten: *Ich lerne Deutsch.*`,
  },
  "doc-akkusativ": {
    ...libraryItems[2],
    source_url: null,
    content_md: `# Präpositionen mit Akkusativ

**durch, für, gegen, ohne, um** verlangen immer den Akkusativ.`,
  },
  [libraryDocId]: {
    ...libraryItems[3],
    source_url: null,
    content_md: `# Ein Tag im Park

Anna wacht um sieben Uhr auf. Sie steht auf, duscht und trinkt eine Tasse Kaffee. Das Wetter ist heute schön: Die Sonne scheint, und der Himmel ist blau. Anna beschließt, in den Park zu gehen.`,
  },
};

let threadSeq = 1;
let messageSeq = 1;

export const threads: ChatThreadSummary[] = [
  {
    id: "thread-1",
    title: "Dativ vs Akkusativ",
    message_count: 2,
    updated_at: "2026-07-30T11:00:00Z",
  },
];

export const threadMessages: Record<string, ChatMessage[]> = {
  "thread-1": [
    {
      id: "msg-1",
      role: "user",
      content:
        "Erkläre mir den Unterschied zwischen Dativ und Akkusativ bei Wechselpräpositionen.",
      created_at: "2026-07-30T10:58:00Z",
    },
    {
      id: "msg-2",
      role: "assistant",
      content:
        'Wechselpräpositionen nehmen Akkusativ bei Bewegung (Wohin?) und Dativ bei Ort (Wo?). Beispiel: „auf den Tisch" (Akk) vs „auf dem Tisch" (Dat).',
      created_at: "2026-07-30T11:00:00Z",
      model: "anthropic/claude-3.5-sonnet",
      sources: [
        {
          id: "src-1",
          document_id: "doc-dativ",
          title: "Wechselpräpositionen — Kurzreferenz",
          snippet: "Akkusativ bei Richtung, Dativ bei Position.",
          score: 0.91,
          page: 2,
          url: null,
        },
      ],
      tool_calls: [
        {
          name: "conjugate_verb",
          args: { verb: "stellen", tense: "praesens" },
          result: {
            verb: "stellen",
            tense: "praesens",
            forms: { ich: "stelle", du: "stellst", er_sie_es: "stellt" },
          },
        },
      ],
      usage: { tokens_in: 820, tokens_out: 210, cost_usd: 0.0042 },
    },
  ],
};

export const vocabItems: VocabItem[] = [
  {
    id: "vocab-1",
    lemma: "der Tisch",
    article: "der",
    plural: "die Tische",
    meaning: "table",
    ipa: "tɪʃ",
    examples: [{ de: "Der Tisch ist groß.", en: "The table is big." }],
    status: "learning",
    due_at: "2026-07-31T08:00:00Z",
    created_at: "2026-07-20T10:00:00Z",
  },
  {
    id: "vocab-2",
    lemma: "mustern",
    article: null,
    plural: null,
    meaning: "to scrutinise",
    ipa: "ˈmʊstɐn",
    examples: [{ de: "Sie musterte ihn kurz.", en: "She looked him over briefly." }],
    status: "new",
    due_at: null,
    created_at: "2026-07-28T10:00:00Z",
  },
];

export const flashcards: FlashcardDue[] = [
  {
    card_id: "card-1",
    vocabulary_id: "vocab-1",
    lemma: "der Tisch",
    meaning: "table",
    examples: [{ de: "Der Tisch ist groß.", en: "The table is big." }],
    ipa: "tɪʃ",
    reps: 2,
    interval_days: 2,
  },
];

export const quizAnswers: Record<string, Record<string, string>> = {
  "quiz-demo": { q1: "dem", q2: "an der", q3: "auf das" },
};

export const pendingQuizzes: Record<string, QuizGenerateResponse> = {};

export const adminDocuments: AdminDocument[] = libraryItems.map((item) => ({
  id: item.id,
  title: item.title,
  source_type: item.source_type,
  source_url: null,
  cefr_level: item.cefr_level,
  skill: item.skill,
  status: "ready" as const,
  error: null,
  chunk_count: item.chunk_count,
  created_at: item.created_at,
  updated_at: item.created_at,
}));

export const aiRoutes: AiRoute[] = [
  {
    task_type: "grammar_explain",
    primary_model: "anthropic/claude-3.5-sonnet",
    fallbacks: ["openai/gpt-4o"],
    params: { temperature: 0.3, max_tokens: 1200 },
    updated_at: "2026-07-01T10:00:00Z",
  },
  {
    task_type: "chat_tutor",
    primary_model: "openai/gpt-4o",
    fallbacks: ["anthropic/claude-3.5-sonnet"],
    params: { temperature: 0.5, max_tokens: 2048 },
    updated_at: "2026-07-01T10:00:00Z",
  },
  {
    task_type: "quiz_generate",
    primary_model: "openai/gpt-4o",
    fallbacks: ["google/gemini-2.0-flash"],
    params: { temperature: 0.4, max_tokens: 1600 },
    updated_at: "2026-07-01T10:00:00Z",
  },
];

export const adminFeeds: AdminFeed[] = [
  {
    id: "feed-1",
    url: "https://example.com/german/rss",
    cefr_level: "B1",
    poll_interval_minutes: 1440,
    last_polled_at: "2026-07-29T06:00:00Z",
    is_active: true,
    items_ingested: 37,
  },
];

export const analysisSnapshot: AnalysisResponse = {
  cefr_level: "B1",
  skills: {
    reading: 0.76,
    listening: 0.71,
    speaking: 0.68,
    writing: 0.88,
    grammar: 0.82,
    vocabulary: 0.64,
  },
  counters: {
    vocab_total: 842,
    vocab_mastered: 500,
    quizzes_taken: 24,
    writings_submitted: 9,
    streak_days: 30,
  },
  activity: Array.from({ length: 30 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (29 - i));
    return {
      day: d.toISOString().slice(0, 10),
      minutes: 10 + (i % 7) * 4,
      xp: 80 + (i % 5) * 20,
    };
  }),
  weak_spots: [
    {
      topic: "dative case",
      accuracy: 0.42,
      attempts: 12,
      recommendation: "Review Dative Case, then retry the quiz.",
      document_id: "doc-dativ",
    },
  ],
  speaking_sessions: [],
  cefr_trend: [
    { day: "2026-07-01", estimate: "A2" },
    { day: "2026-07-15", estimate: "B1" },
  ],
  usage: {
    tokens_in: 184203,
    tokens_out: 52011,
    cost_usd: 0.9312,
    by_model: [{ model: "anthropic/claude-3.5-sonnet", cost_usd: 0.51, calls: 120 }],
    quota: {
      limit_calls: 500,
      used_calls: 213,
      resets_at: "2026-08-01T00:00:00Z",
    },
  },
};

export function uid(prefix: string) {
  return `${prefix}-${++threadSeq}-${Date.now()}`;
}

/** MSW: simulate async document ingestion for admin demos */
export function scheduleMockIngest(docId: string) {
  const doc = adminDocuments.find((d) => d.id === docId);
  if (!doc) return;
  doc.status = "pending";
  setTimeout(() => {
    const d = adminDocuments.find((x) => x.id === docId);
    if (d) d.status = "processing";
  }, 800);
  setTimeout(() => {
    const d = adminDocuments.find((x) => x.id === docId);
    if (d) {
      d.status = "ready";
      d.chunk_count = 24 + Math.floor(Math.random() * 80);
      d.error = null;
      d.updated_at = new Date().toISOString();
    }
  }, 3200);
}

export function scheduleMockReingest(docId: string) {
  const doc = adminDocuments.find((d) => d.id === docId);
  if (!doc) return;
  doc.status = "processing";
  doc.error = null;
  setTimeout(() => {
    const d = adminDocuments.find((x) => x.id === docId);
    if (d) {
      d.status = "ready";
      d.chunk_count += 5;
      d.updated_at = new Date().toISOString();
    }
  }, 2500);
}

export function nextMessageId() {
  return `msg-${++messageSeq}`;
}

export function getThread(id: string): ChatThread | null {
  const messages = threadMessages[id];
  if (!messages) return null;
  const summary = threads.find((t) => t.id === id);
  return { id, title: summary?.title ?? "Chat", messages: [...messages] };
}

export function createThread(title: string): ChatThreadSummary {
  const id = uid("thread");
  const t: ChatThreadSummary = {
    id,
    title,
    message_count: 0,
    updated_at: new Date().toISOString(),
  };
  threads.unshift(t);
  threadMessages[id] = [];
  return t;
}
