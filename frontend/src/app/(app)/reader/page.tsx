"use client";

import { Link } from "@/components/router-link";

import { useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown } from "lucide-react";
import { AudioLines, Pause, Play } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useQuery } from "@tanstack/react-query";
import { readerText } from "@/data/deutschflow";
import { apiFetch } from "@/lib/api";
import type { LibraryDocument, LibraryItem, Paginated, User } from "@/lib/types";
import { splitReaderParagraphs } from "@/lib/reader-content";
import { ReaderDisplaySettings } from "@/components/reader/reader-display-settings";
import { ReaderArticlePage } from "@/components/reader/reader-article-page";
import { useReaderThemeState } from "@/hooks/use-reader-theme-state";
import { countWords, readingMinutes } from "@/lib/reader-content";
import { READER_FONT_SIZE_KEY } from "@/lib/reader-themes";

const ambience = ["Rain on glass", "Café in Wien", "Night train", "Silence"];

function AmbiencePanel({
  sound,
  setSound,
  playing,
  setPlaying,
}: {
  sound: string;
  setSound: (s: string) => void;
  playing: boolean;
  setPlaying: (fn: (p: boolean) => boolean) => void;
}) {
  return (
    <div className="panel space-y-3 rounded-lg p-4">
      <p className="label-mono flex items-center gap-1.5">
        <AudioLines className="size-3" /> Ambience
      </p>
      <div className="grid gap-2">
        {ambience.map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setSound(a)}
            className={`rounded-md px-3 py-2 text-left text-sm transition-colors ${
              sound === a ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"
            }`}
          >
            {a}
          </button>
        ))}
      </div>
      <Button variant="outline" size="sm" className="w-full gap-2" onClick={() => setPlaying((p) => !p)}>
        {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
        {playing ? "Pause" : "Play"} soundscape
      </Button>
    </div>
  );
}

function GlossaryPanel() {
  return (
    <div className="panel rounded-lg p-4">
      <p className="label-mono mb-3">Glossary</p>
      <ul className="space-y-2.5">
        {readerText.glossary.map((g) => (
          <li key={g.term} className="text-sm">
            <div className="flex items-center gap-2">
              <span className="text-signal">{g.term}</span>
              <Badge variant="secondary" className="text-[10px]">
                {g.level}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">{g.gloss}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Pick the story to read: a real library document AT THE LEARNER'S LEVEL.
 *
 * The page used to render a hardcoded demo story labelled "Niveau B2" for
 * everyone — an A1 learner saw a B2 badge that had nothing to do with them or
 * with anything in their course. The badge names the TEXT's level (that is how
 * graded readers work), so the fix is to load a text that matches the learner:
 * their level first, any level in their language second, and the bundled demo
 * story only when the library is empty (fresh install, no corpus yet).
 */
function useReaderDocument() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<User>("/me"),
  });
  const level = me.data?.cefr_level;

  const atMyLevel = useQuery({
    queryKey: ["reader-doc", level],
    enabled: !!level,
    queryFn: () => apiFetch<Paginated<LibraryItem>>(`/library?level=${level}&limit=1`),
  });
  // Nothing graded at the learner's exact level: any document in their target
  // language beats falling back to demo content in the wrong language.
  const anyLevel = useQuery({
    queryKey: ["reader-doc-any"],
    enabled: atMyLevel.isSuccess && atMyLevel.data.items.length === 0,
    queryFn: () => apiFetch<Paginated<LibraryItem>>(`/library?limit=1`),
  });

  const chosen = atMyLevel.data?.items[0] ?? anyLevel.data?.items[0] ?? null;
  const detail = useQuery({
    queryKey: ["reader-doc-detail", chosen?.id],
    enabled: !!chosen,
    queryFn: () => apiFetch<LibraryDocument>(`/library/${chosen!.id}`),
  });

  const settled =
    me.isError ||
    (atMyLevel.isSuccess && atMyLevel.data.items.length === 0 && anyLevel.isSuccess) ||
    detail.isSuccess ||
    detail.isError;

  if (detail.data?.content_md) {
    return {
      docId: chosen!.id,
      title: detail.data.title,
      level: detail.data.cefr_level,
      paragraphs: splitReaderParagraphs(detail.data.content_md),
      isDemo: false,
      settled: true,
    };
  }
  // Demo fallback — only once the queries have actually settled, so the page
  // does not flash B2 demo content at someone whose real text is still loading.
  return {
    docId: null,
    title: readerText.title,
    level: readerText.level,
    paragraphs: readerText.paragraphs,
    isDemo: true,
    settled,
  };
}

export default function ReaderPage() {
  const [theme, setTheme] = useReaderThemeState();
  const [size, setSize] = useState(() =>
    Number(typeof localStorage !== "undefined" ? localStorage.getItem(READER_FONT_SIZE_KEY) ?? "19" : "19"),
  );
  const [sound, setSound] = useState("Rain on glass");
  const [playing, setPlaying] = useState(false);

  const doc = useReaderDocument();
  const wordCount = countWords(doc.paragraphs.join(" "));
  const minutes = readingMinutes(wordCount);

  return (
    <AppShell
      title="Immersive Reader"
      subtitle="Graded stories · themed canvas · ambient sound"
      actions={
        <div className="flex gap-2">
          <Badge variant="outline" className="border-data/40 text-data">
            Niveau {doc.level}
            {doc.isDemo && doc.settled ? " · Beispieltext" : ""}
          </Badge>
          {doc.docId ? (
            <Button asChild variant="secondary" size="sm">
              <Link to="/library/$id" params={{ id: doc.docId }}>
                Open in library
              </Link>
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)] lg:items-start lg:gap-6">
        <div className="sticky top-0 z-20 -mx-1 shrink-0 border-b border-border/50 bg-background/95 px-1 pb-3 pt-0.5 backdrop-blur-sm lg:hidden">
          <ReaderDisplaySettings
            theme={theme}
            onThemeChange={setTheme}
            size={size}
            onSizeChange={setSize}
          />
        </div>

        <aside className="hidden flex-col gap-5 lg:col-start-1 lg:row-start-1 lg:flex">
          <ReaderDisplaySettings
            theme={theme}
            onThemeChange={setTheme}
            size={size}
            onSizeChange={setSize}
          />
          <AmbiencePanel sound={sound} setSound={setSound} playing={playing} setPlaying={setPlaying} />
          <GlossaryPanel />
        </aside>

        <div className="lg:col-start-2">
          <ReaderArticlePage
            theme={theme}
            fontSizePx={size}
            title={doc.title}
            level={doc.level}
            paragraphs={doc.paragraphs}
            footer={
              <>
                {wordCount} Wörter · ca. {minutes} Min. Lesezeit
                {doc.docId ? (
                  <>
                    {" "}· tap-a-word in{" "}
                    <Link
                      to="/library/$id"
                      params={{ id: doc.docId }}
                      className="underline underline-offset-2"
                    >
                      library mode
                    </Link>
                  </>
                ) : null}
              </>
            }
          />
        </div>

        <Collapsible className="panel overflow-hidden rounded-lg lg:hidden">
          <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3">
            <span className="text-sm font-medium">Ambience & glossary</span>
            <ChevronDown className="size-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-4 border-t border-border px-4 pb-4 pt-3">
            <AmbiencePanel sound={sound} setSound={setSound} playing={playing} setPlaying={setPlaying} />
            <GlossaryPanel />
          </CollapsibleContent>
        </Collapsible>
      </div>
    </AppShell>
  );
}
