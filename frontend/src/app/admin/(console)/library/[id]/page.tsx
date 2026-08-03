"use client";

import { Link, useParams } from "@/components/router-link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { AdminShell } from "@/components/admin-shell";
import { DocumentStatusBadge } from "@/components/admin/document-status-badge";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ReaderArticlePage } from "@/components/reader/reader-article-page";
import { useReaderThemeState } from "@/hooks/use-reader-theme-state";
import { apiFetch, ApiError } from "@/lib/api";
import { splitReaderParagraphs } from "@/lib/reader-content";
import type { AdminDocument, LibraryDocument, Paginated } from "@/lib/types";
import { useMemo, useState } from "react";
import { useReaderFontSize } from "@/hooks/use-reader-theme-state";

export default function AdminLibraryPreviewPage() {
  const { id } = useParams() as { id: string };
  const [theme] = useReaderThemeState();
  const [size] = useReaderFontSize();

  const meta = useQuery({
    queryKey: ["admin-documents", "library"],
    queryFn: () => apiFetch<Paginated<AdminDocument>>("/admin/documents?limit=100"),
  });

  const documentMeta = meta.data?.items.find((d) => d.id === id);

  const content = useQuery({
    queryKey: ["library-doc", id],
    queryFn: () => apiFetch<LibraryDocument>(`/library/${id}`),
    enabled: documentMeta?.status === "ready",
    retry: false,
  });

  const paragraphs = useMemo(() => {
    if (!content.data?.content_md) return [];
    return splitReaderParagraphs(content.data.content_md);
  }, [content.data?.content_md]);

  const title = content.data?.title ?? documentMeta?.title ?? "Document";

  return (
    <AdminShell title={title} subtitle="Admin preview · same content learners see when status is ready">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" className="gap-1.5" asChild>
          <Link to="/admin/library">
            <ArrowLeft className="size-3.5" />
            Back to library
          </Link>
        </Button>
        {documentMeta ? <DocumentStatusBadge status={documentMeta.status} /> : null}
        {content.data?.cefr_level ? <CefrBadge level={content.data.cefr_level} /> : null}
        {documentMeta?.status === "ready" ? (
          <Button variant="secondary" size="sm" asChild>
            <a href={`/library/${id}`} target="_blank" rel="noopener noreferrer">
              Open learner view
            </a>
          </Button>
        ) : null}
      </div>

      {meta.isLoading && <Skeleton className="h-64 w-full" />}

      {documentMeta && documentMeta.status !== "ready" && (
        <div className="rounded-lg border border-border bg-card p-6 text-sm">
          <p className="text-muted-foreground">
            This document is not published to the learner library yet (<strong>{documentMeta.status}</strong>
            ).
          </p>
          {documentMeta.error ? <p className="mt-2 text-destructive">{documentMeta.error}</p> : null}
          <p className="mt-4 text-muted-foreground">
            Fix or wait for ingestion on the{" "}
            <Link to="/admin/knowledge-base" className="text-data underline-offset-2 hover:underline">
              knowledge base
            </Link>{" "}
            screen.
          </p>
        </div>
      )}

      {documentMeta?.status === "ready" && content.isError && (
        <ErrorAlert
          message={
            content.error instanceof ApiError && content.error.status === 404
              ? "Ready in admin list but not found in learner library — try re-ingesting."
              : content.error instanceof Error
                ? content.error.message
                : "Could not load content"
          }
          onRetry={() => void content.refetch()}
        />
      )}

      {content.isLoading && documentMeta?.status === "ready" && <Skeleton className="h-96 w-full rounded-lg" />}

      {content.data && (
        <ReaderArticlePage
          theme={theme}
          fontSizePx={size}
          title={content.data.title}
          level={content.data.cefr_level}
          paragraphs={paragraphs}
          footer="Admin preview — learners get word lookup on the same article in Reading mode"
          renderParagraph={(p, i) => (
            <p key={i}>{p}</p>
          )}
        />
      )}
    </AdminShell>
  );
}
