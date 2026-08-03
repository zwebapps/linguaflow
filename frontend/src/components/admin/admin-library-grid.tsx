"use client";

import { Link } from "@/components/router-link";
import { useMemo, useState } from "react";
import { BookOpen, ExternalLink } from "lucide-react";
import { DocumentStatusBadge } from "@/components/admin/document-status-badge";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AdminDocument, DocumentStatus } from "@/lib/types";

const STATUS_OPTIONS: { value: "all" | DocumentStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "ready", label: "Ready (in learner library)" },
  { value: "processing", label: "Processing" },
  { value: "pending", label: "Pending" },
  { value: "failed", label: "Failed" },
];

export function AdminLibraryGrid({ items }: { items: AdminDocument[] }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"all" | DocumentStatus>("all");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter((d) => {
      if (status !== "all" && d.status !== status) return false;
      if (!needle) return true;
      return (
        d.title.toLowerCase().includes(needle) ||
        d.source_type.toLowerCase().includes(needle) ||
        (d.skill?.toLowerCase().includes(needle) ?? false) ||
        (d.source_url?.toLowerCase().includes(needle) ?? false)
      );
    });
  }, [items, q, status]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: items.length };
    for (const d of items) m[d.status] = (m[d.status] ?? 0) + 1;
    return m;
  }, [items]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1.5">
          <Label htmlFor="lib-search" className="text-xs text-muted-foreground">
            Search
          </Label>
          <Input
            id="lib-search"
            placeholder="Title, type, skill, URL…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="max-w-md"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Status</Label>
          <Select value={status} onValueChange={(v) => setStatus(v as typeof status)}>
            <SelectTrigger className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                  {opt.value === "all" ? ` (${counts.all ?? 0})` : ` (${counts[opt.value] ?? 0})`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Showing {filtered.length} of {items.length} documents · Manage ingestion on{" "}
        <Link to="/admin/knowledge-base" className="text-data underline-offset-2 hover:underline">
          Knowledge base
        </Link>
      </p>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="size-10" />}
          title={items.length === 0 ? "No knowledge yet" : "No matches"}
          description={
            items.length === 0
              ? "Upload files or add links from the knowledge base screen."
              : "Try clearing search or changing the status filter."
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((item) => (
            <article
              key={item.id}
              className="flex flex-col rounded-lg border border-border bg-card p-4 transition-shadow hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-2">
                <h2 className="min-w-0 break-all font-display text-sm font-semibold leading-snug [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] overflow-hidden" title={item.title}>
                  {item.title}
                </h2>
                {item.cefr_level ? <CefrBadge level={item.cefr_level} /> : null}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <DocumentStatusBadge status={item.status} />
                <Badge variant="secondary" className="text-[10px]">
                  {item.source_type}
                </Badge>
                {item.skill ? (
                  <Badge variant="outline" className="text-[10px]">
                    {item.skill}
                  </Badge>
                ) : null}
                <Badge variant="outline" className="font-mono text-[10px]">
                  {item.chunk_count} chunks
                </Badge>
              </div>
              {item.status === "failed" && item.error ? (
                <p className="mt-2 line-clamp-2 text-xs text-destructive">{item.error}</p>
              ) : null}
              {item.source_url ? (
                <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">{item.source_url}</p>
              ) : null}
              <div className="mt-4 flex flex-wrap gap-2 border-t border-border/60 pt-3">
                {item.status === "ready" ? (
                  <>
                    <Link
                      to="/admin/library/$id"
                      params={{ id: item.id }}
                      className="text-xs font-medium text-data underline-offset-2 hover:underline"
                    >
                      Preview content
                    </Link>
                    <a
                      href={`/library/${item.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      Learner view
                      <ExternalLink className="size-3" />
                    </a>
                  </>
                ) : (
                  <span className="text-xs text-muted-foreground">Not visible to learners until status is ready</span>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
