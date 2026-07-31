import { useRouter } from "@/components/router-link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { Download } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ChatComposer } from "@/components/chat/chat-composer";
import { MessageBubble, type LiveAssistantState } from "@/components/chat/message-bubble";
import { StatusIndicator } from "@/components/chat/status-indicator";
import { ThreadSidebar } from "@/components/chat/thread-sidebar";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { streamChat } from "@/lib/chat-stream";
import { ApiError } from "@/lib/api";
import type { ChatThread } from "@/lib/types";
import { learnerStatusLabel } from "@/lib/learner-copy";

const SUGGESTIONS = [
  "Explain the dative case",
  "Quiz me on A2 verbs",
  "Conjugate gehen in Präsens",
];

function emptyLive(): LiveAssistantState {
  return {
    content: "",
    status: null,
    sources: [],
    tools: new Map(),
  };
}

export function TutorView({ threadId }: { threadId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [live, setLive] = useState<LiveAssistantState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeThreadRef = useRef<string | null>(threadId ?? null);

  const { data: thread, isLoading } = useQuery({
    queryKey: ["chat-thread", threadId],
    queryFn: () => (threadId ? apiFetch<ChatThread>(`/chat/threads/${threadId}`) : null),
    enabled: Boolean(threadId),
  });

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;
      setError(null);
      setStreaming(true);
      setLive(emptyLive());
      const ac = new AbortController();
      abortRef.current = ac;

      try {
        await streamChat(
          {
            thread_id: activeThreadRef.current,
            message: text.trim(),
          },
          {
            onStart: (d) => {
              activeThreadRef.current = d.thread_id;
              setLive((prev) => ({
                ...(prev ?? emptyLive()),
                model: d.model,
                status: "Thinking…",
              }));
              if (!threadId) {
                router.replace(`/tutor/${d.thread_id}`);
              }
            },
            onStatus: (d) => setLive((p) => (p ? { ...p, status: learnerStatusLabel(d.label) } : p)),
            onToolCall: (d) =>
              setLive((p) => {
                if (!p) return p;
                const tools = new Map(p.tools);
                tools.set(d.id, { ...d, pending: true });
                return { ...p, tools };
              }),
            onToolResult: (d) =>
              setLive((p) => {
                if (!p) return p;
                const tools = new Map(p.tools);
                const prev = tools.get(d.id);
                if (prev) tools.set(d.id, { ...prev, pending: false, result: d });
                return { ...p, tools };
              }),
            onSources: (d) => setLive((p) => (p ? { ...p, sources: d.sources } : p)),
            onToken: (d) =>
              setLive((p) => (p ? { ...p, content: p.content + d.text, status: null } : p)),
            onUsage: (d) =>
              setLive((p) =>
                p
                  ? {
                      ...p,
                      usage: {
                        tokens_in: d.tokens_in,
                        tokens_out: d.tokens_out,
                        cost_usd: d.cost_usd,
                        latency_ms: d.latency_ms,
                        from_cache: d.from_cache,
                      },
                    }
                  : p,
              ),
            onDone: () => {
              setStreaming(false);
              setLive(null);
              qc.invalidateQueries({ queryKey: ["chat-thread", activeThreadRef.current] });
              qc.invalidateQueries({ queryKey: ["chat-threads"] });
            },
            onError: (d) => {
              setError(d.message);
              setStreaming(false);
              setLive(null);
            },
          },
          ac.signal,
        );
      } catch (e) {
        setStreaming(false);
        setLive(null);
        setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
      }
    },
    [router, qc, streaming, threadId],
  );

  return (
    <AppShell
      title="AI Tutor"
      subtitle="Ask in your language or English · answers cite your library · pick up past chats anytime"
      actions={
        threadId ? (
          <Button variant="secondary" size="sm" className="gap-1.5" disabled>
            <Download className="size-3.5" /> Export chat
          </Button>
        ) : undefined
      }
    >
      <div className="grid gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
        <ThreadSidebar
          activeId={threadId ?? activeThreadRef.current}
          onNew={() => {
            activeThreadRef.current = null;
            router.push("/tutor");
          }}
        />

        <section className="space-y-5">
          {isLoading && threadId && (
            <div className="space-y-3">
              <Skeleton className="h-16 w-3/4 ml-auto" />
              <Skeleton className="h-40 w-full" />
            </div>
          )}

          {!threadId && !streaming && (
            <div className="panel rounded-lg p-6">
              <p className="font-display text-lg font-semibold">Start a conversation</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Ask about grammar, vocabulary, or request a quiz — answers include sources and tool
                traces.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button key={s} variant="outline" size="sm" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {thread?.messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}

          {streaming && live && (
            <>
              {live.status && <StatusIndicator label={live.status} />}
              <MessageBubble live={live} />
            </>
          )}

          {error && <ErrorAlert message={error} onRetry={() => setError(null)} />}

          <ChatComposer
            value={draft}
            onChange={setDraft}
            streaming={streaming}
            onSubmit={() => {
              const t = draft;
              setDraft("");
              send(t);
            }}
            onStop={() => abortRef.current?.abort()}
          />
        </section>
      </div>
    </AppShell>
  );
}
