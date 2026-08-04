import { Link } from "@/components/router-link";
import { ChevronDown, Quote } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { learnerMatchScore } from "@/lib/learner-copy";
import type { ChatSource } from "@/lib/types";

type Grouped = {
  document_id: string;
  title: string;
  snippet: string;
  score: number;
  passages: number;
};

/**
 * One row per DOCUMENT, not per retrieved chunk.
 *
 * Retrieval returns the best-matching passages, and on a 500-entry vocabulary
 * PDF all of them come from the same file — the panel listed the same title six
 * times over, each with a near-identical score, which reads as a bug rather
 * than as thorough searching. The strongest passage represents the document and
 * the rest become a count.
 */
function groupByDocument(sources: ChatSource[]): Grouped[] {
  const byDoc = new Map<string, Grouped>();
  for (const source of sources) {
    const seen = byDoc.get(source.document_id);
    if (!seen) {
      byDoc.set(source.document_id, { ...source, passages: 1 });
    } else {
      seen.passages += 1;
      // Keep the snippet belonging to the best-scoring passage, so the preview
      // is the one that actually earned the match.
      if (source.score > seen.score) {
        seen.score = source.score;
        seen.snippet = source.snippet;
      }
    }
  }
  return [...byDoc.values()].sort((a, b) => b.score - a.score);
}

export function SourcesList({ sources }: { sources: ChatSource[] }) {
  const documents = groupByDocument(sources);

  return (
    // Collapsed by default: the answer is what the learner came for. Open, this
    // panel pushed the reply off-screen on a laptop and dominated on mobile.
    <Collapsible className="panel group rounded-lg">
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-4 py-3 text-left text-sm hover:bg-surface-raised/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Quote className="size-3 shrink-0 text-signal" />
        <span className="label-mono">
          From your library ({documents.length})
        </span>
        <ChevronDown
          className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="space-y-2 border-t border-border px-4 py-3">
          {documents.map((doc, i) => (
            <li
              key={doc.document_id}
              className="flex flex-wrap items-center gap-3 rounded-md bg-surface-raised/60 px-3 py-2 text-sm"
            >
              <span className="font-mono text-xs text-signal">[{i + 1}]</span>
              <Link
                to="/library/$id"
                params={{ id: doc.document_id }}
                className="min-w-0 flex-1 truncate text-data hover:underline"
              >
                {doc.title}
              </Link>
              {doc.passages > 1 && (
                <span className="text-xs text-muted-foreground">
                  {doc.passages} passages
                </span>
              )}
              <span className="hidden max-w-[40%] truncate text-xs text-muted-foreground sm:inline">
                {doc.snippet}
              </span>
              <Badge variant="secondary" className="text-[10px]">
                {learnerMatchScore(doc.score)}
              </Badge>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
