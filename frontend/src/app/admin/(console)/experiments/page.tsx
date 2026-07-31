"use client";

import { useQuery } from "@tanstack/react-query";
import { AdminShell } from "@/components/admin-shell";
import { ExperimentsPanel } from "@/components/admin/experiments-panel";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AdminExperiment } from "@/lib/types";

export default function AdminExperimentsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-experiments"],
    queryFn: () => apiFetch<{ experiments: AdminExperiment[] }>("/admin/experiments"),
  });

  return (
    <AdminShell title="A/B experiments" subtitle="RAG retrieval strategy splits and live outcomes">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      {isLoading ? <Skeleton className="h-96 w-full" /> : <ExperimentsPanel experiments={data?.experiments ?? []} />}
    </AdminShell>
  );
}
