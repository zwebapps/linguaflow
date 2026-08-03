"use client";

import { Link, useRouter } from "@/components/router-link";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import type { LibraryItem, Paginated } from "@/lib/types";
import { Library } from "lucide-react";

export default function LibraryPage() {
  const [q, setQ] = useState("");
  // Show the learner's own level first — that is what they set their profile
  // to study at. "All levels" stays one click away for browsing ahead.
  const myLevel = useAuthStore((s) => s.user)?.cefr_level;
  const [level, setLevel] = useState<string | null>(null);
  const effectiveLevel = level ?? myLevel ?? "all";

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["library", q, effectiveLevel],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (effectiveLevel !== "all") params.set("level", effectiveLevel);
      const qs = params.toString();
      return apiFetch<Paginated<LibraryItem>>(`/library${qs ? `?${qs}` : ""}`);
    },
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
        <Select value={effectiveLevel} onValueChange={(v) => setLevel(v)}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["A1", "A2", "B1", "B2", "C1"].map((l) => (
              <SelectItem key={l} value={l}>
                {l}
                {l === myLevel ? " · your level" : ""}
              </SelectItem>
            ))}
            <SelectItem value="all">All levels</SelectItem>
          </SelectContent>
        </Select>
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
          title={effectiveLevel === "all" ? "No content yet" : `Nothing at ${effectiveLevel} yet`}
          description={
            effectiveLevel === "all"
              ? "New readings and grammar sheets will show up here when your course team adds them."
              : "Nothing is graded at this level yet — switch to “All levels” to browse everything in your language."
          }
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
