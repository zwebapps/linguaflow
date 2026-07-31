export const INGEST_MAX_BYTES = 25 * 1024 * 1024;

export const INGEST_FILE_EXTENSIONS = [
  "pdf",
  "epub",
  "docx",
  "md",
  "html",
  "htm",
  "txt",
] as const;

export type IngestLinkType = "web" | "youtube" | "rss";

const extSet = new Set(INGEST_FILE_EXTENSIONS);

export function ingestFileExtension(name: string): string | null {
  const parts = name.split(".");
  if (parts.length < 2) return null;
  const ext = parts.pop()?.toLowerCase();
  if (!ext || !extSet.has(ext as (typeof INGEST_FILE_EXTENSIONS)[number])) return null;
  return ext === "htm" ? "html" : ext;
}

export function validateIngestFile(file: File): string | null {
  if (file.size > INGEST_MAX_BYTES) {
    return "File must be 25 MB or smaller.";
  }
  if (!ingestFileExtension(file.name)) {
    return `Allowed types: ${INGEST_FILE_EXTENSIONS.join(", ")}`;
  }
  return null;
}

export function sourceTypeFromFileName(name: string): string {
  const ext = ingestFileExtension(name);
  if (ext === "htm") return "html";
  return ext ?? "txt";
}
