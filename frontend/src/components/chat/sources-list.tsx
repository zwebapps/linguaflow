import { Link } from "@/components/router-link";
import { Quote } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { learnerMatchScore } from "@/lib/learner-copy";
import type { ChatSource } from "@/lib/types";

export function SourcesList({ sources }: { sources: ChatSource[] }) {
  return (
    <Collapsible defaultOpen className="panel rounded-lg">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm">
        <Quote className="size-3 text-signal" />
        <span className="label-mono">From your library ({sources.length})</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="space-y-2 border-t border-border px-4 py-3">
          {sources.map((c, i) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center gap-3 rounded-md bg-surface-raised/60 px-3 py-2 text-sm"
            >
              <span className="font-mono text-xs text-signal">[{i + 1}]</span>
              <Link
                to="/library/$id"
                params={{ id: c.document_id }}
                className="min-w-0 flex-1 truncate text-data hover:underline"
              >
                {c.title}
              </Link>
              <span className="max-w-[40%] truncate text-xs text-muted-foreground">{c.snippet}</span>
              <Badge variant="secondary" className="text-[10px]">
                {learnerMatchScore(c.score)}
              </Badge>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
