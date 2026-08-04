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
import type { SearchResponse, SearchResult } from "@/lib/types";

/** One card per source document; its matching passages listed beneath. */
function groupByDocument(results: SearchResult[]) {
  const byDoc = new Map<string, { document_id: string; title: string; best: number; hits: SearchResult[] }>();
  for (const r of results) {
    const g = byDoc.get(r.document_id);
    if (g) {
      g.hits.push(r);
      g.best = Math.max(g.best, r.score);
    } else {
      byDoc.set(r.document_id, { document_id: r.document_id, title: r.title, best: r.score, hits: [r] });
    }
  }
  return [...byDoc.values()].sort((a, b) => b.best - a.best);
}

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
            {search.data.results.length} passages in {groupByDocument(search.data.results).length}{" "}
            {groupByDocument(search.data.results).length === 1 ? "document" : "documents"} ·{" "}
            {learnerSearchStrategy(search.data.strategy)} · {search.data.took_ms} ms
          </p>
          {/* Grouped by document: a 58-chunk book matching eight times looked
              like eight duplicate results, because every passage carried the
              same title. One card per source, its passages listed inside. */}
          {groupByDocument(search.data.results).map((group) => (
            <div key={group.document_id} className="panel rounded-lg p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  to="/library/$id"
                  params={{ id: group.document_id }}
                  className="font-display font-semibold hover:underline"
                >
                  {group.title}
                </Link>
                <Badge variant="secondary" className="text-[10px]">
                  {learnerMatchScore(group.best)}
                </Badge>
                {group.hits.length > 1 && (
                  <span className="text-xs text-muted-foreground">
                    {group.hits.length} matching passages
                  </span>
                )}
              </div>
              <ul className="mt-2 space-y-2">
                {group.hits.map((r) => (
                  <li key={r.id} className="text-sm text-muted-foreground">
                    {r.page != null && (
                      <span className="mr-2 font-mono text-[10px] text-muted-foreground/80">
                        p.{r.page}
                      </span>
                    )}
                    {r.snippet}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
