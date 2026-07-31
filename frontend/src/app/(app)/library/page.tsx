"use client";

import { Link, useRouter } from "@/components/router-link";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import type { LibraryItem, Paginated } from "@/lib/types";
import { Library } from "lucide-react";

export default function LibraryPage() {
  const [q, setQ] = useState("");
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["library", q],
    queryFn: () =>
      apiFetch<Paginated<LibraryItem>>(`/library${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

  return (
    <AppShell title="Library" subtitle="Graded readings and lessons for your course languages">
      <div className="mb-6 flex flex-wrap gap-3">
        <Input
          placeholder="Search titles…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-sm"
        />
      </div>
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load library"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-lg" />
          ))}
        </div>
      )}
      {data?.items.length === 0 && (
        <EmptyState
          icon={<Library className="size-10" />}
          title="No content yet"
          description="New readings and grammar sheets will show up here when your course team adds them."
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.items.map((item) => (
          <Link
            key={item.id}
            to="/library/$id"
            params={{ id: item.id }}
            className="panel block rounded-lg p-4 transition-shadow hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-display font-semibold leading-snug">{item.title}</h2>
              <CefrBadge level={item.cefr_level} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="secondary" className="text-[10px]">
                {item.source_type}
              </Badge>
              <Badge variant="outline" className="text-[10px]">
                {item.reading_minutes} min
              </Badge>
            </div>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}
