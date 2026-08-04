"use client";

/**
 * Admin → RAG evaluation. Runs the golden set on demand and shows the metrics.
 *
 * A run is 14 cases × retrieval (+ an LLM judge pass), so the POST only starts
 * it and returns immediately; this page polls while anything is "running".
 * History is kept so a strategy change can be compared against the last run.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FlaskConical, Play, ScrollText } from "lucide-react";
import { AdminShell } from "@/components/admin-shell";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";

type EvalRun = {
  id: string;
  status: "running" | "completed" | "failed";
  strategy: string;
  k: number;
  judge: boolean;
  n_cases: number;
  means: Record<string, number | null> | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
};

type EvalCase = {
  question: string;
  cefr_level: string;
  relevant_doc_titles: string[];
  retrieved_titles: string[];
  hit_rate: number;
  ndcg: number;
  generated_answer: string | null;
  faithfulness: number | null;
  answer_relevancy: number | null;
};

type EvalRunDetail = EvalRun & { cases: EvalCase[] };

/** Per-case judge detail — what was asked, what the model answered, how it scored. */
function JudgeDetail({ runId }: { runId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["admin-eval-run", runId],
    queryFn: () => apiFetch<EvalRunDetail>(`/admin/eval/runs/${runId}`),
  });

  if (isLoading) return <Spinner label="Loading cases…" />;
  if (isError)
    return (
      <ErrorAlert message={error instanceof Error ? error.message : "Could not load cases"} />
    );
  if (!data?.cases.length)
    return <p className="text-sm text-muted-foreground">No per-case detail stored for this run.</p>;

  return (
    <ul className="space-y-3">
      {data.cases.map((c, i) => {
        // The golden set's unanswerable cases have no relevant document by
        // design — they exist to catch confabulation, so they're the most
        // interesting rows to read, not noise to hide.
        const unanswerable = c.relevant_doc_titles.length === 0;
        return (
          <li
            key={i}
            className={`rounded-lg border p-3 ${
              unanswerable ? "border-primary/40 bg-primary/5" : "border-border/70"
            }`}
          >
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="text-[10px]">
                {c.cefr_level}
              </Badge>
              {unanswerable && (
                <Badge variant="secondary" className="text-[10px]">
                  unanswerable by design
                </Badge>
              )}
              {c.faithfulness !== null && (
                <Badge
                  variant={c.faithfulness >= 0.8 ? "secondary" : "destructive"}
                  className="text-[10px]"
                >
                  faithfulness {pct(c.faithfulness)}
                </Badge>
              )}
              {c.answer_relevancy !== null && (
                <Badge variant="outline" className="text-[10px]">
                  relevancy {pct(c.answer_relevancy)}
                </Badge>
              )}
              <span className="font-mono text-[10px] text-muted-foreground">
                hit {c.hit_rate ? "✓" : "✗"} · nDCG {c.ndcg.toFixed(2)}
              </span>
            </div>
            <p className="text-sm font-medium">{c.question}</p>
            {c.generated_answer && (
              <p className="mt-1.5 whitespace-pre-wrap rounded bg-muted/50 p-2 text-xs leading-relaxed">
                {c.generated_answer}
              </p>
            )}
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              <span className="font-medium">Expected:</span>{" "}
              {c.relevant_doc_titles.join(", ") || "— (nothing in the corpus covers this)"}
              {" · "}
              <span className="font-medium">Retrieved:</span>{" "}
              {c.retrieved_titles.slice(0, 4).join(", ") || "none"}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

// Order matters: retrieval quality first, then the generation-side judge.
const METRICS: { key: string; label: string; hint: string }[] = [
  { key: "hit_rate", label: "Hit rate", hint: "Any relevant doc in the top k" },
  { key: "mrr", label: "MRR", hint: "How high the first relevant doc ranked" },
  { key: "ndcg", label: "nDCG", hint: "Ranking quality, rewards relevant docs early" },
  { key: "context_precision", label: "Precision", hint: "Share of retrieved chunks that were relevant" },
  { key: "context_recall", label: "Recall", hint: "Share of relevant docs that were found" },
  { key: "faithfulness", label: "Faithfulness", hint: "Claims supported by context — refusing to guess scores 1.0" },
  { key: "answer_relevancy", label: "Relevancy", hint: "Did the answer address the question" },
];

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

export default function AdminEvaluationPage() {
  const qc = useQueryClient();
  const [strategy, setStrategy] = useState("hybrid");
  const [judge, setJudge] = useState(true);

  // Poll only while a run is in flight — no reason to hammer an idle page.
  // Driven by plain state (set from the fetched rows) rather than reading the
  // query off its own options callback, which silently never re-armed.
  const [polling, setPolling] = useState(false);
  // Which run's per-case judge detail is expanded (null = collapsed).
  const [openCases, setOpenCases] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-eval-runs"],
    queryFn: async () => {
      const rows = await apiFetch<EvalRun[]>("/admin/eval/runs?limit=10");
      setPolling(rows.some((r) => r.status === "running"));
      return rows;
    },
    refetchInterval: polling ? 3000 : false,
  });

  const start = useMutation({
    mutationFn: () =>
      apiFetch<EvalRun>("/admin/eval/runs", {
        method: "POST",
        json: { strategy, k: 6, judge },
      }),
    onSuccess: () => {
      // Arm the poll immediately — don't wait for the refetch to observe it.
      setPolling(true);
      void qc.invalidateQueries({ queryKey: ["admin-eval-runs"] });
    },
  });

  const runs = data ?? [];
  const latest = runs.find((r) => r.status === "completed");
  const active = runs.some((r) => r.status === "running");

  return (
    <AdminShell
      title="RAG evaluation"
      subtitle="Run the golden set and measure retrieval + answer quality"
    >
      <div className="grid w-full gap-6">
        <section className="panel space-y-4 rounded-xl p-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <p className="label-mono">Strategy</p>
              <Select value={strategy} onValueChange={setStrategy} disabled={active}>
                <SelectTrigger className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="hybrid">hybrid (BM25 + dense, RRF)</SelectItem>
                  <SelectItem value="dense">dense (vectors only)</SelectItem>
                  <SelectItem value="keyword">keyword (BM25 only)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <p className="label-mono">LLM judge</p>
              <Select
                value={judge ? "on" : "off"}
                onValueChange={(v) => setJudge(v === "on")}
                disabled={active}
              >
                <SelectTrigger className="w-52">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="on">On — adds faithfulness</SelectItem>
                  <SelectItem value="off">Off — retrieval metrics only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button className="gap-2" disabled={active || start.isPending} onClick={() => start.mutate()}>
              <Play className="size-4" />
              {active ? "Running…" : start.isPending ? "Starting…" : "Run evaluation"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            14 golden-set cases — 12 answerable plus 2 deliberately unanswerable, which score 0 on
            the retrieval metrics by design (so 12/14 ≈ 85.7% is a perfect retrieval result) and
            exist to catch confabulation via faithfulness. A run takes 30–90 seconds
            {judge ? " and spends one extra LLM call per case for the judge" : ""}.
          </p>
          {start.isError && (
            <ErrorAlert
              message={start.error instanceof Error ? start.error.message : "Could not start the run"}
            />
          )}
          {active && <Spinner label="Evaluating the golden set…" />}
        </section>

        {isError && (
          <ErrorAlert
            message={error instanceof Error ? error.message : "Could not load runs"}
            onRetry={() => refetch()}
          />
        )}
        {isLoading && <Spinner label="Loading runs…" />}

        {latest?.means && (
          <section className="panel space-y-4 rounded-xl p-5">
            <div className="flex flex-wrap items-center gap-2">
              <FlaskConical className="size-4 text-primary" />
              <p className="font-display text-lg font-semibold">Latest result</p>
              <Badge variant="secondary">{latest.strategy}</Badge>
              <Badge variant="outline">k={latest.k}</Badge>
              <span className="text-xs text-muted-foreground">
                {new Date(latest.created_at).toLocaleString()} · {latest.n_cases} cases
                {latest.duration_ms ? ` · ${(latest.duration_ms / 1000).toFixed(1)}s` : ""}
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {METRICS.map((m) => (
                <div key={m.key} className="rounded-lg border border-border/70 p-3">
                  <p className="label-mono">{m.label}</p>
                  <p className="font-display text-2xl font-semibold">{pct(latest.means?.[m.key])}</p>
                  <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{m.hint}</p>
                </div>
              ))}
            </div>

            <div className="border-t border-border pt-4">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setOpenCases(openCases === latest.id ? null : latest.id)}
              >
                <ScrollText className="size-3.5" />
                {openCases === latest.id ? "Hide" : "Show"} what the judge saw ({latest.n_cases}{" "}
                cases)
              </Button>
              {openCases === latest.id && (
                <div className="mt-3">
                  <p className="mb-2 text-xs text-muted-foreground">
                    Every case, the answer generated from the retrieved context, and the judge&apos;s
                    scores. The highlighted rows are the unanswerable ones — a faithful answer there
                    admits it doesn&apos;t know instead of inventing a rule.
                  </p>
                  <JudgeDetail runId={latest.id} />
                </div>
              )}
            </div>
          </section>
        )}

        {runs.length > 0 && (
          <section className="panel space-y-3 rounded-xl p-5">
            <p className="label-mono">History — compare strategies and spot regressions</p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">When</th>
                    <th className="py-2 pr-3 font-medium">Strategy</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    {METRICS.map((m) => (
                      <th key={m.key} className="py-2 pr-3 font-medium">
                        {m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} className="border-b border-border/50 last:border-b-0">
                      <td className="py-2 pr-3 whitespace-nowrap text-xs text-muted-foreground">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                      <td className="py-2 pr-3">{r.strategy}</td>
                      <td className="py-2 pr-3">
                        <Badge
                          variant={
                            r.status === "completed"
                              ? "secondary"
                              : r.status === "failed"
                                ? "destructive"
                                : "outline"
                          }
                        >
                          {r.status}
                        </Badge>
                      </td>
                      {METRICS.map((m) => (
                        <td key={m.key} className="py-2 pr-3 font-mono text-xs">
                          {pct(r.means?.[m.key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {runs.some((r) => r.error) && (
              <p className="text-xs text-destructive">
                Last error: {runs.find((r) => r.error)?.error}
              </p>
            )}
          </section>
        )}
      </div>
    </AdminShell>
  );
}
