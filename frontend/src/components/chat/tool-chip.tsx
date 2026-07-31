import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { Wrench } from "lucide-react";
import { ToolResultCard } from "@/components/chat/tool-result-card";
import { learnerToolLabel } from "@/lib/learner-copy";
import type { ChatStreamToolCall, ChatStreamToolResult } from "@/lib/types";

export function ToolChip({
  tool,
}: {
  tool: ChatStreamToolCall & {
    pending: boolean;
    result?: ChatStreamToolResult;
  };
}) {
  return (
    <Collapsible>
      <div className="panel rounded-lg">
        <CollapsibleTrigger className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm">
          <Wrench className="size-3.5 text-signal" />
          <span className="text-xs font-medium">{learnerToolLabel(tool.name)}</span>
          <Badge
            variant="outline"
            className={
              tool.pending
                ? "animate-pulse border-warning/40 text-[10px] text-warning"
                : "border-success/40 text-[10px] text-success"
            }
          >
            {tool.pending ? "Working…" : "Done"}
          </Badge>
          {tool.result && (
            <span className="ml-auto text-xs text-muted-foreground">{tool.result.ms} ms</span>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 border-t border-border px-4 py-3">
          {tool.result?.ok && (
            <ToolResultCard name={tool.name} result={tool.result.result} />
          )}
          {!tool.result?.ok && tool.pending && (
            <p className="text-sm text-muted-foreground">One moment…</p>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
