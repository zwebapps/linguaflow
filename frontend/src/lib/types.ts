/** Types mirrored from API_CONTRACT.md — do not invent shapes here. */

export type CefrLevel = "A1" | "A2" | "B1" | "B2" | "C1";
export type UserRole = "student" | "admin";
export type VocabStatus = "new" | "learning" | "mastered";
export type FlashcardGrade = "again" | "hard" | "good" | "easy";
export type QuizQuestionType = "mcq" | "cloze";
export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type ChatStatusStage = "retrieving" | "thinking" | "calling_tool" | "generating";

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    details?: { field: string; issue: string }[];
    request_id?: string;
  };
};

export type Topic = {
  id: string;
  level: CefrLevel;
  kind: "grammar" | "theme";
  title: string;
  title_en: string;
};

export type TopicsResponse = {
  language: string;
  level: CefrLevel;
  items: Topic[];
};

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  cefr_level: CefrLevel;
  goal?: string;
  learning_style?: string;
  daily_goal_minutes?: number;
  gloss_langs?: string[];
  onboarded: boolean;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: User;
};

export type Paginated<T> = {
  items: T[];
  next_cursor: string | null;
};

export type ChatSource = {
  id: string;
  document_id: string;
  title: string;
  snippet: string;
  score: number;
  page?: number | null;
  url?: string | null;
};

export type ChatToolCallPersisted = {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
};

export type ChatUsage = {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model?: string;
  from_cache?: boolean;
  latency_ms?: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  model?: string;
  sources?: ChatSource[];
  tool_calls?: ChatToolCallPersisted[];
  usage?: ChatUsage;
};

export type ChatThreadSummary = {
  id: string;
  title: string;
  message_count: number;
  updated_at: string;
};

export type ChatThread = {
  id: string;
  title: string;
  messages: ChatMessage[];
};

export type ChatRequest = {
  thread_id: string | null;
  message: string;
  context?: {
    document_id?: string | null;
    topic?: string | null;
    cefr_level?: CefrLevel | null;
  };
  model_override?: string | null;
};

export type LookupWordResult = {
  lemma: string;
  pos: string;
  article: string | null;
  plural: string | null;
  ipa: string;
  audio_url: string;
  meanings: { lang: string; text: string }[];
  examples: { de: string; en: string }[];
  cefr_level: CefrLevel;
  source: "dictionary" | "llm";
};

export type ConjugateResult = {
  verb: string;
  tense: string;
  is_irregular: boolean;
  auxiliary: string;
  forms: Record<string, string>;
  source: string;
};

export type SearchResult = {
  id: string;
  document_id: string;
  title: string;
  snippet: string;
  score: number;
  dense_score?: number;
  keyword_score?: number;
  page?: number | null;
  url?: string | null;
};

export type SearchResponse = {
  query: string;
  strategy: "hybrid" | "dense";
  results: SearchResult[];
  took_ms: number;
};

export type LibraryItem = {
  id: string;
  title: string;
  source_type: string;
  cefr_level: CefrLevel;
  skill: string;
  chunk_count: number;
  reading_minutes: number;
  created_at: string;
};

export type LibraryDocument = LibraryItem & {
  source_url: string | null;
  content_md: string;
};

export type VocabItem = {
  id: string;
  lemma: string;
  article: string | null;
  plural: string | null;
  meaning: string;
  ipa: string;
  examples: { de: string; en: string }[];
  status: VocabStatus;
  due_at: string | null;
  created_at: string;
};

export type FlashcardDue = {
  card_id: string;
  vocabulary_id: string;
  lemma: string;
  meaning: string;
  examples: { de: string; en: string }[];
  ipa: string;
  reps: number;
  interval_days: number;
};

export type FlashcardsDueResponse = {
  items: FlashcardDue[];
  remaining: number;
};

export type QuizQuestion = {
  id: string;
  type: QuizQuestionType;
  prompt: string;
  options: string[] | null;
  hint: string | null;
};

export type QuizGenerateResponse = {
  quiz_id: string;
  topic: string;
  cefr_level: CefrLevel;
  questions: QuizQuestion[];
  sources: { document_id: string; title: string; snippet: string }[];
};

export type QuizSubmitResult = {
  question_id: string;
  correct: boolean;
  expected: string;
  given: string;
  explanation: string;
};

export type QuizSubmitResponse = {
  quiz_id: string;
  score: number;
  correct: number;
  total: number;
  results: QuizSubmitResult[];
  cefr_estimate: CefrLevel;
};

export type WritingCorrection = {
  original: string;
  suggestion: string;
  explanation: string;
  severity: "error" | "warning" | "style";
  offset: number;
  length: number;
};

export type WritingEvaluateResponse = {
  submission_id: string;
  scores: {
    grammar: number;
    vocabulary: number;
    coherence: number;
    overall: number;
  };
  cefr_estimate: CefrLevel;
  corrections: WritingCorrection[];
  improved_version: string;
  suggestions: string[];
  usage: ChatUsage;
};

export type AnalysisResponse = {
  cefr_level: CefrLevel;
  skills: Record<string, number>;
  counters: {
    vocab_total: number;
    vocab_mastered: number;
    quizzes_taken: number;
    writings_submitted: number;
    streak_days: number;
  };
  activity: { day: string; minutes: number; xp: number }[];
  weak_spots: {
    topic: string;
    accuracy: number;
    attempts: number;
    recommendation: string;
    document_id: string | null;
  }[];
  cefr_trend: { day: string; estimate: CefrLevel }[];
  usage: {
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    by_model: { model: string; cost_usd: number; calls: number }[];
    quota: { limit_calls: number; used_calls: number; resets_at: string };
  };
};

export type AdminDocument = {
  id: string;
  title: string;
  source_type: string;
  source_url: string | null;
  cefr_level: CefrLevel | null;
  skill: string | null;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type AiRoute = {
  task_type: string;
  primary_model: string;
  fallbacks: string[];
  params: { temperature?: number; max_tokens?: number };
  updated_at: string;
};

export type AdminModel = {
  id: string;
  name: string;
  context_length: number;
  prompt_usd_per_1k: number;
  completion_usd_per_1k: number;
  supports_tools: boolean;
};

export type AdminFeed = {
  id: string;
  url: string;
  cefr_level: CefrLevel;
  poll_interval_minutes: number;
  last_polled_at: string | null;
  is_active: boolean;
  items_ingested: number;
};

export type AdminUsageResponse = {
  total: {
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    calls: number;
    cache_hit_rate: number;
  };
  series: {
    key: string;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    calls: number;
  }[];
};

export type AdminExperiment = {
  name: string;
  enabled: boolean;
  arms: Record<string, number>;
  description: string | null;
  updated_at: string | null;
};

export type AdminExperimentArmStats = {
  arm: string;
  impressions: number;
  mean_results: number;
  mean_top_score_within_arm: number;
  mean_latency_ms: number;
  zero_result_rate: number;
};

export type AdminExperimentResults = {
  experiment: string;
  total_events: number;
  arms: AdminExperimentArmStats[];
  winner: string | null;
  note: string;
};

/** Live chat stream event payloads */
export type ChatStreamStart = { thread_id: string; message_id: string; model: string };
export type ChatStreamStatus = { stage: ChatStatusStage; label: string };
export type ChatStreamToolCall = { id: string; name: string; args: Record<string, unknown> };
export type ChatStreamToolResult = {
  id: string;
  name: string;
  ok: boolean;
  result: unknown;
  ms: number;
};
export type ChatStreamSources = { sources: ChatSource[] };
export type ChatStreamToken = { text: string };
export type ChatStreamUsage = ChatUsage & { model: string; latency_ms: number };
export type ChatStreamDone = { message_id: string; thread_id: string };
export type ChatStreamError = { code: string; message: string };

/** Speaking — API_CONTRACT §12 */
export type SpeakingScenario = {
  id: string;
  title: string;
  persona: string;
  opening: string;
};

export type SpeakingCorrection = {
  original: string;
  suggestion: string;
  explanation: string;
};

export type SpeakingStreamStart = { thread_id: string; scenario: string };
export type SpeakingStreamStatus = {
  stage: "transcribing" | "thinking" | "scoring" | "speaking";
  label: string;
};
export type SpeakingStreamTranscript = {
  text: string;
  model: string;
  duration_s: number;
};
export type SpeakingStreamScores = {
  pronunciation: number;
  grammar: number;
  fluency: number;
  overall: number;
  pronunciation_is_approximate: boolean;
  notes: string[];
  corrections: SpeakingCorrection[];
  cefr_level: CefrLevel;
};
export type SpeakingStreamAudio = {
  data_uri: string | null;
  media_type?: string;
  model?: string;
  use_browser_tts: boolean;
  text?: string;
  lang?: string;
};
export type SpeakingStreamUsage = {
  model: string;
  stt_model?: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
};
export type SpeakingStreamDone = { message_id: string; thread_id: string };
export type SpeakingStreamError = { code: string; message: string };
