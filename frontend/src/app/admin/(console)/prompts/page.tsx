"use client";

/**
 * Admin → Prompts: the AI's editable voice.
 *
 * Each card is one prompt the platform uses (tutor, quiz author, writing
 * examiner, speaking partner, speaking scorer, Lernpaket author). Saving
 * stores a DB override that takes effect on the NEXT request — no deploy —
 * and Reset deletes it so the code default takes over. The backend validates
 * that every required {placeholder} survives an edit, so a broken template
 * can't reach a learner.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RotateCcw, Save } from "lucide-react";
import { AdminShell } from "@/components/admin-shell";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch } from "@/lib/api";

type PromptItem = {
  key: string;
  title: string;
  description: string;
  placeholders: string[];
  default: string;
  override: string | null;
  active_source: "default" | "override";
  updated_at: string | null;
};

function PromptCard({ item }: { item: PromptItem }) {
  const qc = useQueryClient();
  const active = item.override ?? item.default;
  const [text, setText] = useState(active);
  const [feedback, setFeedback] = useState<string | null>(null);

  // A refetch (e.g. after reset) must refresh the editor too.
  useEffect(() => setText(item.override ?? item.default), [item.override, item.default]);

  const save = useMutation({
    mutationFn: () =>
      apiFetch<PromptItem>(`/admin/prompts/${item.key}`, {
        method: "PUT",
        json: { content: text },
      }),
    onSuccess: () => {
      setFeedback("Saved — live on the next request.");
      void qc.invalidateQueries({ queryKey: ["admin-prompts"] });
    },
    onError: () => setFeedback(null),
  });

  const reset = useMutation({
    mutationFn: () => apiFetch(`/admin/prompts/${item.key}`, { method: "DELETE" }),
    onSuccess: () => {
      setFeedback("Reset to the built-in default.");
      void qc.invalidateQueries({ queryKey: ["admin-prompts"] });
    },
  });

  const dirty = text.trim() !== active.trim();

  return (
    <section className="panel space-y-3 rounded-xl p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-display text-lg font-semibold">{item.title}</h2>
        <Badge variant={item.active_source === "override" ? "default" : "secondary"}>
          {item.active_source === "override" ? "Customised" : "Default"}
        </Badge>
        {item.updated_at && (
          <span className="text-xs text-muted-foreground">
            edited {new Date(item.updated_at).toLocaleString()}
          </span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{item.description}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground">Must keep:</span>
        {item.placeholders.map((ph) => (
          <code key={ph} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
            {"{" + ph + "}"}
          </code>
        ))}
      </div>
      <Textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setFeedback(null);
        }}
        rows={10}
        className="font-mono text-xs leading-relaxed"
        aria-label={`Prompt text for ${item.title}`}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          className="gap-1.5"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          <Save className="size-3.5" />
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={reset.isPending || (item.active_source === "default" && !dirty)}
          onClick={() =>
            item.active_source === "override" ? reset.mutate() : setText(item.default)
          }
        >
          <RotateCcw className="size-3.5" />
          Reset to default
        </Button>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          {text.length}/8000
        </span>
      </div>
      {save.isError && (
        <ErrorAlert
          message={save.error instanceof Error ? save.error.message : "Save failed"}
          onRetry={() => save.mutate()}
        />
      )}
      {feedback && <p className="text-xs text-success">{feedback}</p>}
    </section>
  );
}

export default function AdminPromptsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-prompts"],
    queryFn: () => apiFetch<PromptItem[]>("/admin/prompts"),
  });

  return (
    <AdminShell
      title="Prompts"
      subtitle="The AI's instructions — edit here, live on the next request, no deploy"
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load prompts"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && <Spinner label="Loading prompts…" />}
      <div className="grid max-w-4xl gap-6">
        {data?.map((item) => <PromptCard key={item.key} item={item} />)}
      </div>
    </AdminShell>
  );
}
