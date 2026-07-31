"use client";



import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { ActivityIntro, ActivityWorksheet } from "@/components/learner/activity-surfaces";
import { VocabChallengeGrid, VocabHowToUse } from "@/components/learner/vocab-challenge-grid";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { Paginated, VocabItem, VocabStatus } from "@/lib/types";
import { useState } from "react";
import { Trash2 } from "lucide-react";

const tabs: (VocabStatus | "all")[] = ["all", "new", "learning", "mastered"];

export default function VocabularyPage() {
  const [tab, setTab] = useState<(typeof tabs)[number]>("all");
  const [search, setSearch] = useState("");
  const qc = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["vocab", tab],
    queryFn: () =>
      apiFetch<Paginated<VocabItem>>(
        `/vocab${tab !== "all" ? `?status=${tab}` : ""}`,
      ),
  });

  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/vocab/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vocab"] }),
  });

  const items =
    data?.items.filter((v) =>
      search ? v.lemma.toLowerCase().includes(search.toLowerCase()) : true,
    ) ?? [];

  return (
    <AppShell title="Vocabulary" subtitle="Words saved from reading and tutor">
      <div className="space-y-6">
        <ActivityIntro
          kind="vocabulary"
          subtitle="Pastel day sets and steps — Vitality, Midnight, or Forest theme."
        />

        <ActivityWorksheet className="space-y-4">
          <p className="label-mono">How to use this challenge</p>
          <VocabHowToUse />
          {isLoading ? (
            <Skeleton className="h-40 w-full rounded-lg" />
          ) : (
            <VocabChallengeGrid items={items} />
          )}
        </ActivityWorksheet>

        <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
          <TabsList>
            {tabs.map((t) => (
              <TabsTrigger key={t} value={t} className="capitalize">
                {t}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value={tab} className="mt-4 space-y-4">
            <Input
              placeholder="Search lemma…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-sm"
            />
            {isError && (
              <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
            )}
            <div className="panel rounded-lg">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Lemma</TableHead>
                    <TableHead>Meaning</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((v) => (
                    <TableRow key={v.id}>
                      <TableCell className="font-medium">{v.lemma}</TableCell>
                      <TableCell>{v.meaning}</TableCell>
                      <TableCell className="capitalize">{v.status}</TableCell>
                      <TableCell>
                        <Button variant="ghost" size="icon" onClick={() => del.mutate(v.id)}>
                          <Trash2 className="size-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
