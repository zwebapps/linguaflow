"use client";



import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";
import type { FlashcardGrade, FlashcardsDueResponse } from "@/lib/types";
import { PartyPopper } from "lucide-react";

const grades: FlashcardGrade[] = ["again", "hard", "good", "easy"];

export default function FlashcardsPage() {
  const qc = useQueryClient();
  const [flipped, setFlipped] = useState(false);
  const [index, setIndex] = useState(0);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["flashcards-due"],
    queryFn: () => apiFetch<FlashcardsDueResponse>("/flashcards/due"),
  });

  const grade = useMutation({
    mutationFn: ({ id, g }: { id: string; g: FlashcardGrade }) =>
      apiFetch(`/flashcards/${id}/grade`, { method: "POST", json: { grade: g } }),
    onSuccess: () => {
      setFlipped(false);
      setIndex(0);
      qc.invalidateQueries({ queryKey: ["flashcards-due"] });
    },
  });

  const card = data?.items[index];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!card) return;
      if (e.code === "Space") {
        e.preventDefault();
        setFlipped((f) => !f);
      }
      const n = Number(e.key);
      if (n >= 1 && n <= 4) grade.mutate({ id: card.card_id, g: grades[n - 1] });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, grade]);

  if (!isLoading && data?.items.length === 0) {
    return (
      <AppShell title="Flashcards" subtitle="Spaced repetition review">
        <EmptyState
          icon={<PartyPopper className="size-10" />}
          title="All caught up"
          description="No cards due right now. Come back later or add vocabulary from the library."
        />
      </AppShell>
    );
  }

  const total = data?.items.length ?? 0;
  const progress = total ? ((index + 1) / total) * 100 : 0;

  return (
    <AppShell title="Flashcards" subtitle={`${index + 1} of ${total} · Space to flip · 1–4 to grade`}>
      {isError && (
        <ErrorAlert message={error instanceof Error ? error.message : "Failed"} onRetry={() => refetch()} />
      )}
      {card && (
        <div className="mx-auto max-w-lg space-y-6">
          <Progress value={progress} className="h-2" />
          <button
            type="button"
            className="panel flex min-h-[220px] w-full flex-col items-center justify-center rounded-xl p-8 text-center"
            onClick={() => setFlipped((f) => !f)}
          >
            {!flipped ? (
              <>
                <p className="font-display text-3xl font-semibold">{card.lemma}</p>
                <p className="mt-2 text-sm text-muted-foreground">Tap or Space to flip</p>
              </>
            ) : (
              <>
                <p className="text-xl">{card.meaning}</p>
                <p className="mt-2 font-mono text-sm text-muted-foreground">{card.ipa}</p>
                <p className="mt-4 text-sm italic">{card.examples[0]?.de}</p>
              </>
            )}
          </button>
          <div className="grid grid-cols-4 gap-2">
            {grades.map((g, i) => (
              <Button
                key={g}
                variant="outline"
                className="capitalize"
                disabled={grade.isPending}
                onClick={() => grade.mutate({ id: card.card_id, g })}
              >
                {i + 1}. {g}
              </Button>
            ))}
          </div>
        </div>
      )}
    </AppShell>
  );
}
