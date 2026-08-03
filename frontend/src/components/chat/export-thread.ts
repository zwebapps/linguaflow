import { apiDownload } from "@/lib/api";

/**
 * Download one chat thread in any backend-supported format.
 *
 * Shared by the thread sidebar's per-thread menu and the tutor header's
 * "Export chat" button, so the format list and the blob-download dance live
 * exactly once.
 */
export async function exportThread(id: string, format: "pdf" | "md" | "json" | "csv") {
  const blob = await apiDownload(`/chat/threads/${id}/export?format=${format}`);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `thread-${id}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
