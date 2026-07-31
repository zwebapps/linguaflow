import Markdown from "react-markdown";
import { Sparkle } from "lucide-react";
import { StatusIndicator } from "@/components/chat/status-indicator";
import { SourcesList } from "@/components/chat/sources-list";
import { ToolChip } from "@/components/chat/tool-chip";
import { UsageFooter } from "@/components/chat/usage-footer";
import { learnerStatusLabel } from "@/lib/learner-copy";
import type { ChatMessage, ChatSource, ChatStreamToolCall, ChatStreamToolResult } from "@/lib/types";

export type LiveAssistantState = {
  content: string;
  status: string | null;
  model?: string;
  sources: ChatSource[];
  tools: Map<
    string,
    ChatStreamToolCall & { result?: ChatStreamToolResult; pending: boolean }
  >;
  usage?: ChatMessage["usage"] & { model?: string; latency_ms?: number; from_cache?: boolean };
};

export function MessageBubble({
  message,
  live,
}: {
  message?: ChatMessage;
  live?: LiveAssistantState;
}) {
  if (message?.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg rounded-br-sm bg-primary px-4 py-3 text-sm leading-relaxed text-primary-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  const content = live?.content ?? message?.content ?? "";
  const sources = live?.sources.length ? live.sources : (message?.sources ?? []);
  const tools = live
    ? [...live.tools.values()]
    : (message?.tool_calls?.map((t, i) => ({
        id: `persisted-${i}`,
        name: t.name,
        args: t.args,
        pending: false,
        result: t.result
          ? { id: `persisted-${i}`, name: t.name, ok: true, result: t.result, ms: 0 }
          : undefined,
      })) ?? []);

  return (
    <article className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="grid size-7 place-items-center rounded-md bg-secondary">
          <Sparkle className="size-3.5 text-signal" />
        </div>
        <span className="label-mono">LinguaFlow Tutor</span>
      </div>

      <div
        className="prose prose-invert max-w-none text-[15px] leading-7 text-foreground/90 prose-p:my-2"
        aria-live="polite"
      >
        <Markdown>{content}</Markdown>
      </div>

      {live?.status && <StatusIndicator label={learnerStatusLabel(live.status)} />}

      {tools.length > 0 && (
        <div className="space-y-2">
          {tools.map((t) => (
            <ToolChip key={t.id} tool={t} />
          ))}
        </div>
      )}

      {sources.length > 0 && <SourcesList sources={sources} />}

      {(live?.usage || message?.usage) && (
        <UsageFooter usage={live?.usage ?? message!.usage!} />
      )}
    </article>
  );
}
