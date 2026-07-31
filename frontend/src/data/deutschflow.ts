export type Citation = {
  id: string;
  source: string;
  section: string;
  score: number;
  retriever: "dense" | "bm25" | "hybrid";
};

export type ToolCall = {
  name: string;
  schema: string;
  status: "ok" | "running";
  latency: string;
  args: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  cefr?: string;
  content: string;
  citations?: Citation[];
  tools?: ToolCall[];
  judge?: { accuracy: number; relevance: number; cefr: number; hallucination: number };
  meta?: { model: string; tokens: number; cost: string; latency: string };
};

export const conversation: Message[] = [
  {
    id: "m1",
    role: "user",
    content:
      "Erkläre mir den Unterschied zwischen Dativ und Akkusativ bei Wechselpräpositionen — und gib mir eine kurze Übung auf B1-Niveau.",
  },
  {
    id: "m2",
    role: "assistant",
    cefr: "B1",
    content:
      'Wechselpräpositionen (an, auf, hinter, in, neben, über, unter, vor, zwischen) nehmen den Akkusativ, wenn eine Richtung beschrieben wird (Wohin?), und den Dativ, wenn ein Ort beschrieben wird (Wo?).\n\nAkkusativ — Bewegung: „Ich stelle die Lampe auf den Tisch."\nDativ — Position: „Die Lampe steht auf dem Tisch."\n\nMerkhilfe: Wechsel des Ortes → Akkusativ. Kein Wechsel → Dativ.',
    citations: [
      {
        id: "c1",
        source: "Duden — Die Grammatik, 10. Auflage",
        section: "§ 1482 Wechselpräpositionen",
        score: 0.912,
        retriever: "hybrid",
      },
      {
        id: "c2",
        source: "Goethe-Zertifikat B1 Wortliste",
        section: "Lokale Präpositionen, S. 44",
        score: 0.874,
        retriever: "dense",
      },
      {
        id: "c3",
        source: "CEFR Companion Volume 2020",
        section: "Grammatical accuracy B1",
        score: 0.803,
        retriever: "bm25",
      },
    ],
    tools: [
      {
        name: "grammar_parser",
        schema: "mcp://linguaflow/grammar.parse",
        status: "ok",
        latency: "218 ms",
        args: '{ "sentence": "Ich stelle die Lampe auf den Tisch.", "level": "B1" }',
      },
      {
        name: "quiz_generator",
        schema: "mcp://linguaflow/quiz.generate",
        status: "ok",
        latency: "742 ms",
        args: '{ "topic": "Wechselpräpositionen", "level": "B1", "items": 5 }',
      },
    ],
    judge: { accuracy: 96, relevance: 93, cefr: 91, hallucination: 2 },
    meta: {
      model: "anthropic/claude-3.5-sonnet",
      tokens: 1842,
      cost: "$0.0113",
      latency: "1.94 s",
    },
  },
];

export const quizItems = [
  { prompt: "Der Hund läuft ___ Garten. (in)", answer: "in den", case: "Akkusativ" },
  { prompt: "Das Bild hängt ___ Wand. (an)", answer: "an der", case: "Dativ" },
  { prompt: "Sie setzt sich ___ Sofa. (auf)", answer: "auf das", case: "Akkusativ" },
];

export const retrievalPipeline = [
  { step: "Query translation", detail: "DE ⇄ EN normalisation", ms: 84 },
  { step: "Query expansion", detail: "3 paraphrases generated", ms: 141 },
  { step: "Dense search", detail: "text-embedding-3-small · Qdrant", ms: 96 },
  { step: "BM25 lexical", detail: "k1 1.4 · b 0.72", ms: 37 },
  { step: "Reciprocal rank fusion", detail: "top-k 8 → 3", ms: 12 },
];

export const readerText = {
  title: "Der Zauberlehrling im Maschinenraum",
  level: "B2",
  paragraphs: [
    "Der alte Bahnhof von Leipzig lag still im Morgennebel, als Jonas mit seinem Koffer aus dem Zug stieg. Er hatte diese Stadt seit zwölf Jahren nicht mehr gesehen, und doch erkannte er sofort den Geruch von Regen auf altem Sandstein.",
    '„Entschuldigung, wissen Sie, wo die Nikolaistraße ist?" fragte er eine Frau, die neben dem Zeitungskiosk stand. Sie musterte ihn kurz und deutete dann nach links. „Immer geradeaus, dann an der Ampel rechts. Sie können es nicht verfehlen."',
    "Während er ging, dachte er an die Worte seines Großvaters: Sprache ist kein Werkzeug, sondern ein Ort. Wer eine Sprache verliert, verliert eine Adresse in der Welt. Damals hatte Jonas das für Poesie gehalten. Heute klang es wie eine Warnung.",
    "Am Ende der Straße stand das Haus noch immer, mit derselben grünen Tür und demselben verrosteten Briefkasten. Er atmete tief ein und klopfte.",
  ],
  glossary: [
    { term: "der Morgennebel", gloss: "morning fog", level: "B1" },
    { term: "mustern", gloss: "to scrutinise, look over", level: "B2" },
    { term: "verfehlen", gloss: "to miss (a target)", level: "B2" },
    { term: "verrostet", gloss: "rusted", level: "B2" },
  ],
};

export const judgeRuns = [
  { id: "run_9f2a", model: "claude-3.5-sonnet", acc: 96, rel: 93, cefr: 91, hall: 2 },
  { id: "run_7c31", model: "gpt-4o-mini", acc: 88, rel: 90, cefr: 84, hall: 7 },
  { id: "run_5b80", model: "llama-3.1-70b", acc: 81, rel: 86, cefr: 79, hall: 11 },
  { id: "run_2d17", model: "mistral-large", acc: 84, rel: 82, cefr: 80, hall: 9 },
];

export const usageSeries = [
  { day: "Mo", tokens: 42000, cost: 0.52 },
  { day: "Di", tokens: 58000, cost: 0.71 },
  { day: "Mi", tokens: 51000, cost: 0.63 },
  { day: "Do", tokens: 73000, cost: 0.94 },
  { day: "Fr", tokens: 88000, cost: 1.18 },
  { day: "Sa", tokens: 39000, cost: 0.48 },
  { day: "So", tokens: 46000, cost: 0.57 },
];

export const cefrCoverage = [
  { level: "A1", sessions: 34 },
  { level: "A2", sessions: 51 },
  { level: "B1", sessions: 88 },
  { level: "B2", sessions: 67 },
  { level: "C1", sessions: 29 },
];
