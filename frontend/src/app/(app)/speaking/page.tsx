"use client";

import { Link } from "@/components/router-link";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { SpeakingSession } from "@/components/voice/speaking-session";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import type { SpeakingScenario } from "@/lib/types";

export default function SpeakingPage() {
  const user = useAuthStore((s) => s.user);
  const level = user?.cefr_level ?? "B1";

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["speaking-scenarios"],
    queryFn: () => apiFetch<SpeakingScenario[]>("/speaking/scenarios"),
  });

  return (
    <AppShell
      title="Speaking practice"
      subtitle="Practice in your target language · live conversation · pronunciation guidance"
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load scenarios"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && <Skeleton className="h-[520px] w-full rounded-2xl" />}
      {data && data.length > 0 && (
        <SpeakingSession scenarios={data} cefrLevel={level} />
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No scenarios configured.{" "}
          <Link to="/tutor" className="text-primary underline">
            Use text chat
          </Link>{" "}
          instead.
        </p>
      )}
    </AppShell>
  );
}
