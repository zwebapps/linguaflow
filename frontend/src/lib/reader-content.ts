/** Markdown / plain-text helpers for reading mode (no external media). */
export function stripMarkdownHeading(block: string): string {
  return block.replace(/^#+\s*/, "").trim();
}

export function splitReaderParagraphs(content: string): string[] {
  return content
    .split(/\n\n+/)
    .map((p) => stripMarkdownHeading(p))
    .filter(Boolean);
}

export type GlossaryEntry = { term: string; gloss: string; level: string };

const GLOSSAR_HEADING_RE = /^#{1,4}\s*glossar\s*$/im;
// `- **der Morgennebel** (B1) — morning fog` · level optional · — – or - as separator
const GLOSSAR_LINE_RE = /^[-*]\s*\*\*(.+?)\*\*\s*(?:\((A1|A2|B1|B2|C1)\))?\s*[—–-]\s*(.+)$/;

/**
 * Split a document into its reading body and its `## Glossar` section.
 *
 * The glossary used to be a hardcoded demo list (B1/B2 words shown to an A1
 * learner reading an A1 text). Now each authored text carries its own
 * glossary; entries without an explicit per-word level inherit the TEXT's
 * level, so an A1 story shows A1 cards.
 */
export function extractGlossary(
  content: string,
  fallbackLevel: string,
): { body: string; glossary: GlossaryEntry[] } {
  const match = GLOSSAR_HEADING_RE.exec(content);
  if (!match) return { body: content, glossary: [] };

  const body = content.slice(0, match.index).trimEnd();
  const glossary: GlossaryEntry[] = [];
  for (const raw of content.slice(match.index + match[0].length).split("\n")) {
    const line = GLOSSAR_LINE_RE.exec(raw.trim());
    if (!line) continue;
    glossary.push({ term: line[1].trim(), level: line[2] ?? fallbackLevel, gloss: line[3].trim() });
  }
  // A heading with no parseable entries: keep the body split, drop the section.
  return { body, glossary };
}

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

export function readingMinutes(wordCount: number, wpm = 140): number {
  return Math.max(1, Math.round(wordCount / wpm));
}
