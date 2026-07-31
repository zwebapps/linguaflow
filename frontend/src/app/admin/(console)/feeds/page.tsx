"use client";



import { useQuery } from "@tanstack/react-query";
import { AdminShell } from "@/components/admin-shell";
import { FeedsPanel } from "@/components/admin/feeds-panel";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AdminFeed } from "@/lib/types";

export default function FeedsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-feeds"],
    queryFn: () => apiFetch<{ items: AdminFeed[] }>("/admin/feeds"),
  });

  return (
    <AdminShell title="RSS feeds" subtitle="Poll intervals and items ingested">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      {isLoading ? <Skeleton className="h-48 w-full" /> : <FeedsPanel items={data?.items ?? []} />}
    </AdminShell>
  );
}
