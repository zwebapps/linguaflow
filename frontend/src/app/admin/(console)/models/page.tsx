"use client";



import { AdminShell } from "@/components/admin-shell";
import { ModelRouteEditor } from "@/components/admin/model-route-editor";
import { ErrorAlert } from "@/components/shared/error-alert";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { AiRoute } from "@/lib/types";

export default function ModelsPage() {
  const { isError, error, refetch } = useQuery({
    queryKey: ["admin-routes"],
    queryFn: () => apiFetch<{ routes: AiRoute[] }>("/admin/ai-routes"),
  });

  return (
    <AdminShell title="AI routes" subtitle="Task type → primary model, fallbacks, and parameters">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      <ModelRouteEditor />
    </AdminShell>
  );
}
