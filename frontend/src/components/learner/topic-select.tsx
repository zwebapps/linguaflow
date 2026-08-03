"use client";

/**
 * Topic picker for "start learning" surfaces (quiz, writing).
 *
 * The dropdown is fed by GET /topics at the LEARNER's level — the syllabus for
 * the level they chose in their profile, nothing above or below it. Free text
 * survives behind the "Custom topic…" item (and is the whole control when a
 * language has no syllabus yet), because the registry is a menu, not a wall.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";
import type { CefrLevel, Topic, TopicsResponse } from "@/lib/types";

const CUSTOM = "__custom__";

export function useTopics(level: CefrLevel | undefined) {
  return useQuery({
    queryKey: ["topics", level],
    enabled: !!level,
    queryFn: () => apiFetch<TopicsResponse>(`/topics?level=${level}`),
  });
}

type TopicSelectProps = {
  level: CefrLevel;
  value: string;
  /** Receives the canonical topic title; `meta` is set when it came off the list. */
  onChange: (topic: string, meta?: Topic) => void;
};

export function TopicSelect({ level, value, onChange }: TopicSelectProps) {
  const { data, isLoading } = useTopics(level);
  const items = data?.items ?? [];
  const [custom, setCustom] = useState(false);

  // Preselect the first topic of the learner's level once the syllabus loads,
  // so "open the page → start" works without typing anything.
  useEffect(() => {
    if (!custom && !value && items.length > 0) onChange(items[0].title, items[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [custom, value, items]);

  // No syllabus for this language yet — free text is the honest fallback.
  if (!isLoading && items.length === 0) {
    return (
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g. dative case"
      />
    );
  }

  const selectedId = custom
    ? CUSTOM
    : (items.find((t) => t.title === value)?.id ?? (value ? CUSTOM : ""));
  const grammar = items.filter((t) => t.kind === "grammar");
  const themes = items.filter((t) => t.kind === "theme");

  return (
    <div className="space-y-2">
      <Select
        value={selectedId || undefined}
        onValueChange={(v) => {
          if (v === CUSTOM) {
            setCustom(true);
            onChange("");
            return;
          }
          setCustom(false);
          const t = items.find((x) => x.id === v);
          if (t) onChange(t.title, t);
        }}
      >
        <SelectTrigger>
          <SelectValue placeholder={isLoading ? "Loading topics…" : "Choose a topic"} />
        </SelectTrigger>
        <SelectContent>
          {grammar.length > 0 && (
            <SelectGroup>
              <SelectLabel>Grammar · {level}</SelectLabel>
              {grammar.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.title} — {t.title_en}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
          {themes.length > 0 && (
            <SelectGroup>
              <SelectLabel>Themes · {level}</SelectLabel>
              {themes.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.title} — {t.title_en}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
          <SelectItem value={CUSTOM}>Custom topic…</SelectItem>
        </SelectContent>
      </Select>
      {custom && (
        <Input
          autoFocus
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Type your own topic…"
        />
      )}
    </div>
  );
}
