"use client";

import { Link } from "@/components/router-link";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { learnerMatchScore, learnerSearchStrategy } from "@/lib/learner-copy";
import type { SearchResponse } from "@/lib/types";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: (q: string) =>
      apiFetch<SearchResponse>("/tools/search", {
        method: "POST",
        json: { query: q, cefr_level: null, skill: null, k: 8 },
      }),
  });

  return (
    <AppShell title="Search" subtitle="Find lessons and readings in your library">
      <form
        className="flex max-w-xl gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate(query.trim());
        }}
      >
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="dative prepositions…" />
        <Button type="submit" disabled={search.isPending}>
          {search.isPending ? "Searching…" : "Search"}
        </Button>
      </form>
      {search.isPending && (
        <div className="mt-6">
          <Spinner label="Searching your library…" />
        </div>
      )}
      {search.isError && (
        <div className="mt-4">
          <ErrorAlert message={search.error.message} onRetry={() => search.mutate(query)} />
        </div>
      )}
      {search.data && (
        <div className="mt-6 space-y-3">
          <p className="label-mono">
            {search.data.results.length} results · {learnerSearchStrategy(search.data.strategy)} ·{" "}
            {search.data.took_ms} ms
          </p>
          {search.data.results.map((r) => (
            <Link
              key={r.id}
              to="/library/$id"
              params={{ id: r.document_id }}
              className="panel block rounded-lg p-4 hover:bg-secondary/30"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-display font-semibold">{r.title}</span>
                <Badge variant="secondary" className="text-[10px]">
                  {learnerMatchScore(r.score)}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">{r.snippet}</p>
            </Link>
          ))}
        </div>
      )}
    </AppShell>
  );
}
