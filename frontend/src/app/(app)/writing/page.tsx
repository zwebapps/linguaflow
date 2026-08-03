"use client";



import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ActivityIntro, ActivityWorksheet } from "@/components/learner/activity-surfaces";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { UsageFooter } from "@/components/chat/usage-footer";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { writingTextSchema } from "@/lib/validation";
import type { Topic, WritingEvaluateResponse } from "@/lib/types";
import { TopicSelect } from "@/components/learner/topic-select";

/** A picked topic becomes a concrete writing task; free text stays editable. */
function promptForTopic(title: string, meta?: Topic): string {
  if (!title.trim()) return "";
  if (meta?.kind === "grammar") {
    return `Schreiben Sie 5–8 Sätze und verwenden Sie dabei: ${title} (${meta.title_en}).`;
  }
  return `Schreiben Sie einen kurzen Text zum Thema „${title}“.`;
}

export default function WritingPage() {
  // Feedback targets the level the learner set in their profile — the page
  // used to hardcode B1 for everyone.
  const level = useAuthStore((s) => s.user)?.cefr_level ?? "A1";
  const [topic, setTopic] = useState("");
  const [prompt, setPrompt] = useState("Describe your weekend.");
  const [text, setText] = useState("");
  const [result, setResult] = useState<WritingEvaluateResponse | null>(null);

  const evaluate = useMutation({
    mutationFn: () =>
      apiFetch<WritingEvaluateResponse>("/writing/evaluate", {
        method: "POST",
        json: { prompt, text, target_level: level },
      }),
    onSuccess: setResult,
  });

  const validation = writingTextSchema.safeParse(text);

  return (
    <AppShell title="Writing" subtitle="Practice in your target language · feedback on grammar and style">
      <div className="space-y-6">
        <ActivityIntro
          kind="writing"
          subtitle="Prompt, level, and lined writing area — worksheet-style practice that follows your Sepia, Midnight, or Forest theme."
        />
        <div className="grid gap-6 lg:grid-cols-2">
        <ActivityWorksheet className="space-y-4">
          <div className="flex items-center justify-between">
            <Label className="text-[var(--worksheet-fg)]">Your level</Label>
            <div className="flex items-center gap-2">
              <CefrBadge level={level} />
              <span className="text-xs" style={{ color: "var(--worksheet-muted)" }}>
                change it in Settings
              </span>
            </div>
          </div>
          <div className="space-y-2">
            <Label className="text-[var(--worksheet-fg)]">Topic</Label>
            <TopicSelect
              level={level}
              value={topic}
              onChange={(t, meta) => {
                setTopic(t);
                const p = promptForTopic(t, meta);
                if (p) setPrompt(p);
              }}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-[var(--worksheet-fg)]">Prompt</Label>
            <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} className="border-[var(--worksheet-line)] bg-[var(--worksheet-card)]" />
          </div>
          <div className="space-y-2">
            <Label className="text-[var(--worksheet-fg)]">Your text</Label>
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              className="writing-pad-lines min-h-[14rem] border-[var(--worksheet-line)] bg-[var(--worksheet-card)] leading-[1.65rem]"
            />
            <p className="font-mono text-xs" style={{ color: "var(--worksheet-muted)" }}>
              {text.length}/5000
            </p>
            {!validation.success && text.length > 0 && (
              <p className="text-xs text-destructive">{validation.error.errors[0]?.message}</p>
            )}
          </div>
          {evaluate.isError && (
            <ErrorAlert message={evaluate.error.message} onRetry={() => evaluate.mutate()} />
          )}
          <Button disabled={!validation.success || evaluate.isPending} onClick={() => evaluate.mutate()}>
            {evaluate.isPending ? <Spinner label="Checking your text…" /> : "Get feedback"}
          </Button>
        </ActivityWorksheet>

        <div className="space-y-4">
          {evaluate.isPending && (
            <div className="panel space-y-3 rounded-lg p-5">
              <Spinner label="Analyzing grammar, vocabulary, and coherence…" />
              <Progress value={45} className="h-2 animate-pulse" />
            </div>
          )}
          {result && (
            <>
              <div className="panel rounded-lg p-5">
                <div className="mb-4 flex items-center gap-2">
                  <p className="font-display text-lg font-semibold">Scores</p>
                  <CefrBadge level={result.cefr_estimate} />
                </div>
                {Object.entries(result.scores).map(([k, v]) => (
                  <div key={k} className="mb-3">
                    <div className="flex justify-between text-xs capitalize">
                      <span>{k}</span>
                      <span>{Math.round(v * 100)}%</span>
                    </div>
                    <Progress value={v * 100} className="mt-1 h-1.5" />
                  </div>
                ))}
                <UsageFooter usage={result.usage} />
              </div>
              <div className="panel space-y-3 rounded-lg p-5">
                <p className="label-mono">Corrections</p>
                {result.corrections.map((c, i) => (
                  <div key={i} className="text-sm">
                    <p>
                      <span className="text-destructive line-through">{c.original}</span> →{" "}
                      <span className="text-success">{c.suggestion}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">{c.explanation}</p>
                  </div>
                ))}
              </div>
              <div className="panel rounded-lg p-5">
                <p className="label-mono mb-2">Improved version</p>
                <p className="text-sm leading-relaxed">{result.improved_version}</p>
              </div>
            </>
          )}
        </div>
        </div>
      </div>
    </AppShell>
  );
}
