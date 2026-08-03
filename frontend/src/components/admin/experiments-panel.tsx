"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch } from "@/lib/api";
import type { AdminExperiment, AdminExperimentResults } from "@/lib/types";

const DEFAULT_NAME = "retrieval_strategy_v1";

/** Share of total traffic for one arm, over however many arms exist. */
function pctOf(arms: Record<string, number>, arm: string) {
  const total = Object.values(arms).reduce((s, w) => s + Math.max(0, w), 0) || 1;
  return Math.round((Math.max(0, arms[arm] ?? 0) / total) * 100);
}

export function ExperimentsPanel({
  experiments,
  availableArms,
}: {
  experiments: AdminExperiment[];
  /** What an arm may be — served by the API from the retriever's own list, so
   *  this dropdown can never offer a strategy the backend would reject. */
  availableArms: string[];
}) {
  const queryClient = useQueryClient();
  const selected =
    experiments.find((e) => e.name === DEFAULT_NAME) ?? experiments[0] ?? null;

  const [name, setName] = useState(selected?.name ?? DEFAULT_NAME);
  const [enabled, setEnabled] = useState(selected?.enabled ?? false);
  // Dynamic: one entry per arm, strategy chosen from a dropdown. The previous
  // panel hardcoded exactly hybrid+dense, so a third strategy in the backend
  // was unreachable from the UI.
  const [arms, setArms] = useState<Record<string, number>>(
    selected?.arms ?? { hybrid: 0.5, dense: 0.5 },
  );
  const [description, setDescription] = useState(selected?.description ?? "");

  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setEnabled(selected.enabled);
    setArms(selected.arms);
    setDescription(selected.description ?? "");
  }, [selected]);

  const unusedArms = useMemo(
    () => availableArms.filter((a) => !(a in arms)),
    [availableArms, arms],
  );

  function renameArm(from: string, to: string) {
    setArms((prev) => {
      if (to === from || to in prev) return prev;
      const next: Record<string, number> = {};
      // Preserve row order — a rename must not shuffle the list under the admin.
      for (const [k, w] of Object.entries(prev)) next[k === from ? to : k] = w;
      return next;
    });
  }

  const results = useQuery({
    queryKey: ["admin-experiment-results", name],
    queryFn: () => apiFetch<AdminExperimentResults>(`/admin/experiments/${encodeURIComponent(name)}/results`),
    enabled: Boolean(name),
  });

  const save = useMutation({
    mutationFn: () =>
      apiFetch<AdminExperiment>(`/admin/experiments/${encodeURIComponent(name)}`, {
        method: "PUT",
        json: {
          enabled,
          arms,
          description: description.trim() || null,
        },
      }),
    onSuccess: () => {
      toast.success(enabled ? "Experiment saved and running" : "Experiment saved (disabled)");
      void queryClient.invalidateQueries({ queryKey: ["admin-experiments"] });
      void results.refetch();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
  });

  if (!selected) {
    return <p className="text-sm text-muted-foreground">No experiments configured.</p>;
  }

  return (
    <div className="space-y-8">
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-sm font-semibold">RAG strategy A/B</h3>
            <p className="mt-1 max-w-xl text-xs text-muted-foreground">
              Stable per-learner assignment between <strong>hybrid</strong> (BM25 + dense) and{" "}
              <strong>dense</strong> retrieval. Outcomes are logged to <code className="text-data">rag_events</code> during tutor chat.
            </p>
          </div>
          <Badge variant={enabled ? "default" : "secondary"}>{enabled ? "Running" : "Off"}</Badge>
        </div>

        <div className="mt-5 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="exp-name">Experiment id</Label>
            <Input id="exp-name" value={name} readOnly className="font-mono text-sm" />
          </div>

          <div className="flex items-center justify-between gap-4 rounded-md border border-border/60 px-3 py-2">
            <div>
              <p className="text-sm font-medium">Enable experiment</p>
              <p className="text-xs text-muted-foreground">When off, all users get the default search strategy.</p>
            </div>
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enable experiment" />
          </div>

          <div className="space-y-3">
            {Object.entries(arms).map(([arm, weight]) => (
              <div key={arm} className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)_auto] sm:items-center">
                <Select value={arm} onValueChange={(v) => renameArm(arm, v)}>
                  <SelectTrigger aria-label={`Strategy for this arm`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {/* The current strategy plus whatever is not already an arm —
                        two rows can never select the same strategy. */}
                    {[arm, ...unusedArms].map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="space-y-1">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>weight</span>
                    <span className="font-mono">{pctOf(arms, arm)}% traffic</span>
                  </div>
                  <Slider
                    value={[weight]}
                    min={0}
                    max={1}
                    step={0.05}
                    onValueChange={(v) => setArms((prev) => ({ ...prev, [arm]: v[0] }))}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={Object.keys(arms).length <= 1}
                  onClick={() =>
                    setArms((prev) => {
                      const next = { ...prev };
                      delete next[arm];
                      return next;
                    })
                  }
                >
                  Remove
                </Button>
              </div>
            ))}
            {unusedArms.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setArms((prev) => ({ ...prev, [unusedArms[0]]: 0.5 }))}
              >
                + Add arm ({unusedArms.join(", ")} available)
              </Button>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="exp-desc">Notes (optional)</Label>
            <Textarea
              id="exp-desc"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Why this split, target metric, stop date…"
            />
          </div>

          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save configuration"}
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-display text-sm font-semibold">Live results</h3>
            <p className="text-xs text-muted-foreground">{results.data?.note ?? "Load tutor traffic to populate arms."}</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => void results.refetch()}
            disabled={results.isFetching}
          >
            <RefreshCw className={`size-3.5 ${results.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {results.isError && (
          <p className="text-sm text-destructive">{results.error instanceof Error ? results.error.message : "Failed to load results"}</p>
        )}

        {results.isLoading && <p className="text-sm text-muted-foreground">Loading results…</p>}

        {results.data && (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              {results.data.total_events} events
              {results.data.winner && (
                <>
                  {" "}
                  · Leading arm: <span className="font-mono text-data">{results.data.winner}</span>
                </>
              )}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Arm</TableHead>
                  <TableHead className="text-right">Impressions</TableHead>
                  <TableHead className="text-right">Mean results</TableHead>
                  <TableHead className="text-right">Empty rate</TableHead>
                  <TableHead className="text-right">Latency ms</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.data.arms.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground">
                      No rag_events yet — use the AI Tutor with retrieval enabled.
                    </TableCell>
                  </TableRow>
                ) : (
                  results.data.arms.map((arm) => (
                    <TableRow key={arm.arm}>
                      <TableCell className="font-mono">{arm.arm}</TableCell>
                      <TableCell className="text-right">{arm.impressions}</TableCell>
                      <TableCell className="text-right">{arm.mean_results.toFixed(2)}</TableCell>
                      <TableCell className="text-right">{(arm.zero_result_rate * 100).toFixed(1)}%</TableCell>
                      <TableCell className="text-right">{arm.mean_latency_ms.toFixed(0)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </>
        )}
      </div>

      {experiments.length > 1 && (
        <div className="text-xs text-muted-foreground">
          Other configs: {experiments.filter((e) => e.name !== name).map((e) => e.name).join(", ")}
        </div>
      )}
    </div>
  );
}
