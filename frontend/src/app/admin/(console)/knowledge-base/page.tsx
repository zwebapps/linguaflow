"use client";



import { useQuery } from "@tanstack/react-query";
import { AdminShell } from "@/components/admin-shell";
import { DocumentsTable } from "@/components/admin/documents-table";
import { LinkForm } from "@/components/admin/link-form";
import { UploadDropzone } from "@/components/admin/upload-dropzone";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AdminDocument, Paginated } from "@/lib/types";

export default function KnowledgeBasePage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-documents"],
    queryFn: () => apiFetch<Paginated<AdminDocument>>("/admin/documents"),
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      return items.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false;
    },
  });

  return (
    <AdminShell title="Knowledge base" subtitle="Upload files, add links, and monitor ingestion">
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      <div className="space-y-6">
        <div className="grid gap-4 lg:grid-cols-2">
          <UploadDropzone />
          <LinkForm />
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-4 font-display text-sm font-semibold">Documents</h3>
          {isLoading ? <Skeleton className="h-48 w-full" /> : <DocumentsTable items={data?.items ?? []} />}
        </div>
      </div>
    </AdminShell>
  );
}
