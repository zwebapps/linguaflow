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
import { writingTextSchema } from "@/lib/validation";
import type { CefrLevel, WritingEvaluateResponse } from "@/lib/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function WritingPage() {
  const [prompt, setPrompt] = useState("Describe your weekend.");
  const [text, setText] = useState("");
  const [level, setLevel] = useState<CefrLevel>("B1");
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
          <div className="space-y-2">
            <Label className="text-[var(--worksheet-fg)]">Prompt</Label>
            <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} className="border-[var(--worksheet-line)] bg-[var(--worksheet-card)]" />
          </div>
          <div className="space-y-2">
            <Label className="text-[var(--worksheet-fg)]">Target level</Label>
            <Select value={level} onValueChange={(v) => setLevel(v as CefrLevel)}>
              <SelectTrigger className="border-[var(--worksheet-line)] bg-[var(--worksheet-card)]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["A1", "A2", "B1", "B2", "C1"].map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
