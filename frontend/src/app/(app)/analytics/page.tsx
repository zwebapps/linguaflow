"use client";



import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BookOpen, PenLine, Scale, TrendingUp } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cefrCoverage, judgeRuns, usageSeries } from "@/data/deutschflow";
import { apiFetch } from "@/lib/api";
import type { AnalysisResponse } from "@/lib/types";
import { ErrorAlert } from "@/components/shared/error-alert";

const kpis = [
  { label: "Grammar", valueKey: "grammar" as const, icon: Scale },
  { label: "Vocabulary", valueKey: "vocabulary" as const, icon: TrendingUp },
  { label: "Reading", valueKey: "reading" as const, icon: BookOpen },
  { label: "Writing", valueKey: "writing" as const, icon: PenLine },
];

const tooltipStyle = {
  background: "oklch(0.23 0.015 250)",
  border: "1px solid oklch(0.31 0.016 250)",
  borderRadius: 6,
  fontSize: 12,
  color: "oklch(0.95 0.006 250)",
};

export default function AnalyticsPage() {
  const { data, isError, error, refetch } = useQuery({
    queryKey: ["analysis"],
    queryFn: () => apiFetch<AnalysisResponse>("/analysis"),
  });

  const kpiValues = data
    ? {
        grammar: `${Math.round((data.skills.grammar ?? 0) * 100)}%`,
        vocabulary: `${Math.round((data.skills.vocabulary ?? 0) * 100)}%`,
        reading: `${Math.round((data.skills.reading ?? 0) * 100)}%`,
        writing: `${Math.round((data.skills.writing ?? 0) * 100)}%`,
      }
    : null;

  return (
    <AppShell
      title="Your progress"
      subtitle="Skills, study habits, and how well tutor answers fit your level"
      actions={
        <Badge variant="outline" className="text-xs">
          Last 7 days
        </Badge>
      }
    >
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.label} className="panel rounded-lg p-4">
              <div className="flex items-center justify-between">
                <p className="label-mono">{k.label}</p>
                <k.icon className="size-4 text-signal" strokeWidth={1.75} />
              </div>
              <p className="mt-3 font-display text-3xl font-semibold">
                {kpiValues ? kpiValues[k.valueKey] : "—"}
              </p>
            </div>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <div className="panel rounded-lg p-5">
            <p className="label-mono mb-5">Study activity this week</p>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={usageSeries}>
                  <CartesianGrid stroke="oklch(0.31 0.016 250)" strokeDasharray="3 3" />
                  <XAxis dataKey="day" stroke="oklch(0.68 0.014 250)" fontSize={11} />
                  <YAxis stroke="oklch(0.68 0.014 250)" fontSize={11} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Line
                    type="monotone"
                    dataKey="tokens"
                    name="Activity"
                    stroke="oklch(0.79 0.155 74)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel rounded-lg p-5">
            <p className="label-mono mb-5">Sessions by CEFR level</p>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={cefrCoverage}>
                  <CartesianGrid stroke="oklch(0.31 0.016 250)" strokeDasharray="3 3" />
                  <XAxis dataKey="level" stroke="oklch(0.68 0.014 250)" fontSize={11} />
                  <YAxis stroke="oklch(0.68 0.014 250)" fontSize={11} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "transparent" }} />
                  <Bar dataKey="sessions" fill="oklch(0.76 0.115 195)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="panel rounded-lg p-5">
          <p className="label-mono mb-4">Answer quality checks (sample)</p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Session</TableHead>
                <TableHead>Helper</TableHead>
                <TableHead className="text-right">Accuracy</TableHead>
                <TableHead className="text-right">Helpfulness</TableHead>
                <TableHead className="text-right">Level fit</TableHead>
                <TableHead className="text-right">Unsure parts</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {judgeRuns.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="text-xs text-muted-foreground">{r.id.replace("run_", "Session ")}</TableCell>
                  <TableCell className="text-xs">{r.model.split("-")[0] ?? r.model}</TableCell>
                  <TableCell className="text-right">{r.acc}%</TableCell>
                  <TableCell className="text-right">{r.rel}%</TableCell>
                  <TableCell className="text-right">{r.cefr}%</TableCell>
                  <TableCell
                    className={`text-right ${r.hall <= 5 ? "text-success" : "text-warning"}`}
                  >
                    {r.hall}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </AppShell>
  );
}
