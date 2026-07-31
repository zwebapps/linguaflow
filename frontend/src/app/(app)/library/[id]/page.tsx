"use client";

import { Link, useParams } from "@/components/router-link";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { LibraryDocument, LookupWordResult } from "@/lib/types";
import { ReaderDisplaySettings } from "@/components/reader/reader-display-settings";
import { ReaderArticlePage } from "@/components/reader/reader-article-page";
import { useReaderThemeState } from "@/hooks/use-reader-theme-state";
import { splitReaderParagraphs } from "@/lib/reader-content";
import { READER_FONT_SIZE_KEY } from "@/lib/reader-themes";

export default function LibraryReaderPage() {
  const { id } = useParams() as { id: string };
  const [theme, setTheme] = useReaderThemeState();
  const [size, setSize] = useState(() =>
    Number(typeof localStorage !== "undefined" ? localStorage.getItem(READER_FONT_SIZE_KEY) ?? "19" : "19"),
  );
  const [lookup, setLookup] = useState<{ word: string; data?: LookupWordResult; loading: boolean } | null>(
    null,
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["library-doc", id],
    queryFn: () => apiFetch<LibraryDocument>(`/library/${id}`),
  });

  const saveVocab = useMutation({
    mutationFn: (lemma: string) => apiFetch("/vocab", { method: "POST", json: { lemma, source_document_id: id } }),
    onSuccess: (_, lemma) => toast.success(`Added ${lemma} to your vocabulary`),
  });

  const lookupWord = useMutation({
    mutationFn: (lemma: string) =>
      apiFetch<LookupWordResult>("/tools/lookup-word", { method: "POST", json: { lemma, gloss_langs: ["en"] } }),
  });

  const paragraphs = useMemo(() => {
    if (!data?.content_md) return [];
    return splitReaderParagraphs(data.content_md);
  }, [data?.content_md]);

  async function onWordClick(word: string) {
    const lemma = word.replace(/[^a-zA-ZäöüßÄÖÜ-]/g, "");
    if (lemma.length < 2) return;
    setLookup({ word: lemma, loading: true });
    try {
      const data = await lookupWord.mutateAsync(lemma);
      setLookup({ word: lemma, data, loading: false });
    } catch {
      setLookup(null);
    }
  }

  return (
    <AppShell
      title={data?.title ?? "Reading mode"}
      subtitle="Tap a word for dictionary lookup"
      actions={data?.cefr_level && <CefrBadge level={data.cefr_level} />}
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load document"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && <Skeleton className="h-96 w-full rounded-lg" />}
      {data && (
        <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)] lg:items-start lg:gap-6">
          <div className="sticky top-0 z-20 -mx-1 shrink-0 border-b border-border/50 bg-background/95 px-1 pb-3 pt-0.5 backdrop-blur-sm lg:hidden">
            <ReaderDisplaySettings
              theme={theme}
              onThemeChange={setTheme}
              size={size}
              onSizeChange={setSize}
            />
          </div>
          <aside className="hidden lg:col-start-1 lg:row-start-1 lg:block">
            <ReaderDisplaySettings
              theme={theme}
              onThemeChange={setTheme}
              size={size}
              onSizeChange={setSize}
            />
          </aside>
          <div className="lg:col-start-2">
            <ReaderArticlePage
              theme={theme}
              fontSizePx={size}
              title={data.title}
              level={data.cefr_level}
              paragraphs={paragraphs}
              footer="Tap any word for dictionary lookup · save to vocabulary"
              renderParagraph={(p, i) => (
                <p key={i}>
                  {p.split(/(\s+)/).map((chunk, j) => {
                    if (!chunk.trim()) return chunk;
                    return (
                      <Popover key={`${i}-${j}`}>
                        <PopoverTrigger asChild>
                          <button
                            type="button"
                            className="rounded-sm hover:bg-[color-mix(in_srgb,var(--reader-fg)_12%,transparent)]"
                            onClick={() => onWordClick(chunk)}
                          >
                            {chunk}
                          </button>
                        </PopoverTrigger>
                        <PopoverContent className="w-72">
                          {lookup?.word === chunk.replace(/[^a-zA-ZäöüßÄÖÜ-]/g, "") && lookup.loading ? (
                            <Spinner label="Looking up…" />
                          ) : lookup?.data ? (
                            <div className="space-y-2 text-sm">
                              <p className="font-display font-semibold">{lookup.data.lemma}</p>
                              <p className="font-mono text-xs">{lookup.data.ipa}</p>
                              <p>{lookup.data.meanings[0]?.text}</p>
                              <div className="flex gap-2 pt-2">
                                <Button size="sm" variant="secondary" onClick={() => saveVocab.mutate(lookup.data!.lemma)}>
                                  Save
                                </Button>
                                <Button size="sm" asChild variant="outline">
                                  <Link to="/tutor" search={{ prefill: lookup.data.lemma }}>
                                    Ask AI
                                  </Link>
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">Tap to lookup</p>
                          )}
                        </PopoverContent>
                      </Popover>
                    );
                  })}
                </p>
              )}
            />
          </div>
        </div>
      )}
    </AppShell>
  );
}
