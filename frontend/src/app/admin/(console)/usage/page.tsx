"use client";



import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AdminShell } from "@/components/admin-shell";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { apiFetch } from "@/lib/api";
import type { AdminUsageResponse } from "@/lib/types";

type GroupBy = "day" | "model" | "task" | "user";

function defaultFrom() {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
}

function defaultTo() {
  return new Date().toISOString().slice(0, 10);
}

export default function AdminUsagePage() {
  const [groupBy, setGroupBy] = useState<GroupBy>("day");
  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);

  const queryKey = useMemo(() => ["admin-usage", groupBy, from, to] as const, [groupBy, from, to]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey,
    queryFn: () =>
      apiFetch<AdminUsageResponse>(
        `/admin/usage?group_by=${groupBy}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
      ),
  });

  return (
    <AdminShell title="Usage & cost" subtitle="Platform-wide tokens, spend, and cache efficiency">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Group by</Label>
          <ToggleGroup
            type="single"
            value={groupBy}
            onValueChange={(v) => {
              if (v) setGroupBy(v as GroupBy);
            }}
            className="justify-start"
          >
            <ToggleGroupItem value="day" aria-label="Group by day">
              Day
            </ToggleGroupItem>
            <ToggleGroupItem value="model" aria-label="Group by model">
              Model
            </ToggleGroupItem>
            <ToggleGroupItem value="task" aria-label="Group by task">
              Task
            </ToggleGroupItem>
            <ToggleGroupItem value="user" aria-label="Group by user">
              User
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="flex flex-wrap gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="usage-from" className="text-xs">
              From
            </Label>
            <Input id="usage-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="w-40" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="usage-to" className="text-xs">
              To
            </Label>
            <Input id="usage-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="w-40" />
          </div>
        </div>
      </div>

      {isLoading && <Skeleton className="h-64 w-full" />}

      {data && (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Cost (USD)" value={`$${data.total.cost_usd.toFixed(2)}`} />
            <Stat label="API calls" value={String(data.total.calls)} />
            <Stat
              label="Tokens in / out"
              value={`${(data.total.tokens_in / 1000).toFixed(0)}k / ${(data.total.tokens_out / 1000).toFixed(0)}k`}
            />
            <Stat label="Cache hit rate" value={`${Math.round(data.total.cache_hit_rate * 100)}%`} />
          </div>
          <div className="h-72 rounded-lg border border-border bg-card p-4">
            <ResponsiveContainer width="100%" height="100%">
              {/* `name` carries the resolved label for user grouping — the raw
                  key is a UUID nobody can read on an axis. */}
              <BarChart data={data.series.map((p) => ({ ...p, name: p.label ?? p.key }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.3 0.02 260)" />
                <XAxis dataKey="name" fontSize={11} tick={{ fill: "oklch(0.7 0.02 260)" }} />
                <YAxis fontSize={11} tick={{ fill: "oklch(0.7 0.02 260)" }} />
                <Tooltip />
                <Bar dataKey="cost_usd" fill="oklch(0.76 0.115 195)" name="Cost USD" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <p className="label-mono mb-3">
              Breakdown by {groupBy === "user" ? "learner" : groupBy}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">
                      {groupBy === "user" ? "Learner" : groupBy === "day" ? "Day" : groupBy}
                    </th>
                    <th className="py-2 pr-3 text-right font-medium">Calls</th>
                    <th className="py-2 pr-3 text-right font-medium">Tokens in / out</th>
                    <th className="py-2 text-right font-medium">Cost (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.series]
                    .sort((a, b) => b.cost_usd - a.cost_usd)
                    .map((p) => (
                      <tr key={p.key} className="border-b border-border/50 last:border-b-0">
                        <td className="py-2 pr-3">
                          <span>{p.label ?? p.key}</span>
                          {p.label && p.label !== p.key && (
                            // Keep the id visible but subordinate — support
                            // still needs it to look a specific account up.
                            <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                              {p.key.slice(0, 8)}…
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right font-mono text-xs">{p.calls}</td>
                        <td className="py-2 pr-3 text-right font-mono text-xs">
                          {p.tokens_in.toLocaleString()} / {p.tokens_out.toLocaleString()}
                        </td>
                        <td className="py-2 text-right font-mono text-xs">
                          ${p.cost_usd.toFixed(4)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </AdminShell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg font-medium">{value}</p>
    </div>
  );
}
