"use client";

import { useQuery } from "@tanstack/react-query";
import { AdminShell } from "@/components/admin-shell";
import { AdminLibraryGrid } from "@/components/admin/admin-library-grid";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AdminDocument, Paginated } from "@/lib/types";

export default function AdminLibraryPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-documents", "library"],
    queryFn: () => apiFetch<Paginated<AdminDocument>>("/admin/documents?limit=100"),
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      return items.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false;
    },
  });

  return (
    <AdminShell title="Library" subtitle="All curated knowledge — every status, learner-ready and in pipeline">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      {isLoading ? <Skeleton className="h-96 w-full" /> : <AdminLibraryGrid items={data?.items ?? []} />}
    </AdminShell>
  );
}
