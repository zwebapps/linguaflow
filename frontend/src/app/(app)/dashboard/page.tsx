"use client";

import { Link } from "@/components/router-link";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Flame, MessagesSquare, PenLine } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import {
  VitalityActivityList,
  VitalityDailyGoal,
  VitalityStatTile,
} from "@/components/learner/vitality-ui";
import { LearningBackdrop } from "@/components/learning-backdrop";
import { StatCard } from "@/components/shared/stat-card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useAppThemeId } from "@/hooks/use-app-theme";
import type { AnalysisResponse } from "@/lib/types";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function todayMinutes(activity: AnalysisResponse["activity"]): number {
  const today = new Date().toISOString().slice(0, 10);
  const row = activity.find((a) => a.day.startsWith(today) || a.day === today);
  if (row) return row.minutes;
  const last = activity[activity.length - 1];
  return last?.minutes ?? 0;
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const appTheme = useAppThemeId();
  const vitality = appTheme === "classroom";

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["analysis"],
    queryFn: () => apiFetch<AnalysisResponse>("/analysis"),
  });

  const goalMin = user?.daily_goal_minutes ?? 20;
  const minutesToday = data ? todayMinutes(data.activity) : 0;
  const goalPct = Math.min(100, Math.round((minutesToday / goalMin) * 100) || (vitality ? 75 : 65));

  const firstName = user?.display_name?.split(/\s+/)[0] ?? "learner";

  return (
    <AppShell
      title={vitality ? `${greeting()}, ${firstName}!` : "Dashboard"}
      subtitle={
        vitality
          ? "Here's your learning summary for today"
          : `Good to see you, ${user?.display_name ?? "learner"}`
      }
      actions={user?.cefr_level && <CefrBadge level={user.cefr_level} />}
    >
      <div className="relative min-h-full">
      <LearningBackdrop />
      <div className="relative z-10">
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load dashboard"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      )}
      {data && vitality && (
        <div className="mx-auto max-w-5xl space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <VitalityStatTile pastel="sky" label="Words saved" value={String(data.counters.vocab_total)} hint={`${data.counters.vocab_mastered} mastered`} icon={BookOpen} />
            <VitalityStatTile pastel="pink" label="Streak" value={`${data.counters.streak_days}d`} hint="Keep showing up" icon={Flame} />
            <VitalityStatTile pastel="green" label="Quizzes" value={String(data.counters.quizzes_taken)} icon={MessagesSquare} />
            <VitalityStatTile pastel="plum" label="Writing pieces" value={String(data.counters.writings_submitted)} icon={PenLine} />
          </div>
          <VitalityDailyGoal
            percent={goalPct}
            message={`You're ${goalPct}% toward your ${goalMin}-minute daily goal. Keep it up!`}
            action={
              <Button variant="link" className="h-auto p-0 text-primary" asChild>
                <Link to="/analytics">View details →</Link>
              </Button>
            }
          />
          <VitalityActivityList
            items={[
              { emoji: "📖", title: "Reader · graded text", time: "Suggested · morning", meta: "10 min" },
              { emoji: "💬", title: "AI Tutor check-in", time: "Flexible", meta: "15 min" },
              { emoji: "✍️", title: "Writing practice", time: "Afternoon", meta: `${goalMin} min` },
            ]}
          />
          <div className="neo-card flex flex-wrap items-center justify-between gap-4 rounded-xl p-5">
            <div>
              <p className="font-display text-lg font-semibold">Ask the tutor</p>
              <p className="text-sm text-muted-foreground">Clear answers tied to your library texts</p>
            </div>
            <Button asChild className="rounded-xl shadow-sm">
              <Link to="/tutor">Open tutor</Link>
            </Button>
          </div>
        </div>
      )}
      {data && !vitality && (
        <div className="mx-auto max-w-5xl space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Words saved"
              value={String(data.counters.vocab_total)}
              hint={`${data.counters.vocab_mastered} mastered`}
              icon={BookOpen}
            />
            <StatCard label="Streak" value={`${data.counters.streak_days}d`} hint="Keep showing up" icon={Flame} />
            <StatCard label="Quizzes" value={String(data.counters.quizzes_taken)} icon={MessagesSquare} />
            <StatCard label="Writing pieces" value={String(data.counters.writings_submitted)} icon={PenLine} />
          </div>
          <div className="panel rounded-lg p-5">
            <p className="label-mono">Daily goal</p>
            <p className="mt-2 text-sm text-muted-foreground">
              You&apos;re {goalPct}% toward your {goalMin}-minute daily goal.
            </p>
            <Progress value={goalPct} className="mt-3 h-2" />
            <Button variant="link" className="mt-2 h-auto p-0 text-primary" asChild>
              <Link to="/analytics">View details →</Link>
            </Button>
          </div>
          <div className="panel flex flex-wrap items-center justify-between gap-4 rounded-lg p-5">
            <div>
              <p className="font-display text-lg font-semibold">Ask the tutor</p>
              <p className="text-sm text-muted-foreground">Clear answers tied to your library texts</p>
            </div>
            <Button asChild className="rounded-xl shadow-sm">
              <Link to="/tutor">Open tutor</Link>
            </Button>
          </div>
        </div>
      )}
      </div>
      </div>
    </AppShell>
  );
}
