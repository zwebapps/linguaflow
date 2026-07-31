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

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

export function readingMinutes(wordCount: number, wpm = 140): number {
  return Math.max(1, Math.round(wordCount / wpm));
}
