"use client";

/** The vocabulary shelf: every imported word list, with entry counts. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@/components/router-link";
import { BookA } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { CefrLevel } from "@/lib/types";

type WordlistSummary = {
  id: string;
  kind: "wordlist" | "verbchart";
  title: string;
  cefr_level: CefrLevel | null;
  entries: number;
  created_at: string;
};

export default function WordListsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["word-lists"],
    queryFn: () => apiFetch<WordlistSummary[]>("/wordlists"),
  });

  return (
    <AppShell
      title="Word lists"
      subtitle="Vocabulary tables you can browse, search and test yourself on"
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load word lists"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
      )}
      {data?.length === 0 && (
        <EmptyState
          icon={<BookA className="size-10" />}
          title="No word lists yet"
          description="Vocabulary tables appear here automatically when a list-style document is added to the library."
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((list) => (
          <Link
            key={list.id}
            to="/word-lists/$id"
            params={{ id: list.id }}
            className="panel block rounded-lg p-4 transition-colors hover:border-primary/40"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-display font-semibold">{list.title}</span>
              {list.cefr_level && <CefrBadge level={list.cefr_level} />}
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              {list.entries.toLocaleString()}{" "}
              {list.kind === "verbchart" ? "verbs · conjugation chart" : "words"}
            </p>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}
