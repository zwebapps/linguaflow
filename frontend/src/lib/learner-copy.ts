/** Learner-facing labels — hide ops/RAG/engineering terms in the student app. */

const TOOL_LABELS: Record<string, string> = {
  conjugate_verb: "Verb conjugation",
  lookup_word: "Dictionary",
  search_knowledge_base: "Library search",
  grammar_parser: "Grammar check",
  quiz_generator: "Quiz builder",
  grammar_explain: "Grammar explanation",
};

export function learnerToolLabel(apiName: string): string {
  return TOOL_LABELS[apiName] ?? apiName.replace(/_/g, " ");
}

const STATUS_REPLACEMENTS: [RegExp, string][] = [
  [/searching knowledge base/i, "Searching your library"],
  [/knowledge base/i, "your library"],
  [/calling tool/i, "Using a learning helper"],
  [/calling (\w+)/i, "Looking up $1"],
  [/retrieving/i, "Finding relevant lessons"],
  [/generating/i, "Writing your answer"],
  [/thinking/i, "Thinking"],
];

export function learnerStatusLabel(label: string): string {
  let out = label;
  for (const [re, repl] of STATUS_REPLACEMENTS) {
    out = out.replace(re, repl);
  }
  return out;
}

export function learnerSearchStrategy(strategy: string): string {
  switch (strategy) {
    case "hybrid":
      return "Smart search";
    case "dense":
      return "By meaning";
    case "bm25":
      return "By keywords";
    default:
      return strategy;
  }
}

export function learnerMatchScore(score: number): string {
  return `${Math.round(score * 100)}% match`;
}
