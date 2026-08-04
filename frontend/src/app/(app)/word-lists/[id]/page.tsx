"use client";

/**
 * One word list: browse/search the entries, or test yourself on them.
 *
 * The test is built server-side from the list and graded server-side — the
 * response carries no answer key, so the page genuinely cannot reveal answers
 * early even if you read its source.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "@/components/router-link";
import { GraduationCap, RotateCcw, Search, Sparkles } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { apiFetch } from "@/lib/api";
import type { CefrLevel } from "@/lib/types";

type Entry = {
  index: string;
  term: string;
  gloss: string;
  urdu: string;
  hindi: string;
  roman: string;
};

type Detail = {
  id: string;
  title: string;
  cefr_level: CefrLevel | null;
  source_url: string | null;
  total: number;
  entries: Entry[];
};

type TestQuestion = { id: string; term: string; options: string[] };
type TestResponse = { document_id: string; title: string; questions: TestQuestion[] };
type SubmitResult = {
  question_id: string;
  term: string;
  correct: boolean;
  expected: string;
  given: string;
};
type AddCardsResponse = {
  added: number;
  skipped_existing: number;
  not_in_list: number;
  capped: boolean;
};

type SubmitResponse = {
  score: number;
  correct: number;
  total: number;
  results: SubmitResult[];
};

export default function WordListDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [q, setQ] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [test, setTest] = useState<TestResponse | null>(null);
  const [result, setResult] = useState<SubmitResponse | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["word-list", id, q],
    queryFn: () =>
      apiFetch<Detail>(`/wordlists/${id}${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

  const startTest = useMutation({
    mutationFn: () => apiFetch<TestResponse>(`/wordlists/${id}/test?n=10`),
    onSuccess: (t) => {
      setTest(t);
      setAnswers({});
      setResult(null);
    },
  });

  // Turning the words you just got wrong into spaced-repetition cards is the
  // whole point of testing — without this the deck stayed empty no matter how
  // much vocabulary you imported.
  const addCards = useMutation({
    mutationFn: (terms: string[]) =>
      apiFetch<AddCardsResponse>(`/wordlists/${id}/flashcards`, {
        method: "POST",
        json: { terms },
      }),
  });

  const submit = useMutation({
    mutationFn: () =>
      apiFetch<SubmitResponse>("/wordlists/submit", {
        method: "POST",
        json: {
          document_id: id,
          // The id IS the term — the server looks the meaning up.
          answers: (test?.questions ?? []).map((qq) => ({
            question_id: qq.id,
            value: answers[qq.id] ?? "",
          })),
        },
      }),
    onSuccess: setResult,
  });

  const showUrdu = data?.entries.some((e) => e.urdu);
  const showHindi = data?.entries.some((e) => e.hindi);
  const showRoman = data?.entries.some((e) => e.roman);

  return (
    <AppShell
      title={data?.title ?? "Word list"}
      subtitle={data ? `${data.total.toLocaleString()} entries` : "Loading…"}
      actions={data?.cefr_level ? <CefrBadge level={data.cefr_level} /> : undefined}
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load this list"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && <Spinner label="Loading words…" />}

      {/* ── Test mode ─────────────────────────────────────────────────── */}
      {test && !result && (
        <div className="mb-6 space-y-4">
          <p className="label-mono">Self-test · {test.questions.length} words</p>
          {test.questions.map((question, i) => (
            <div key={question.id} className="panel rounded-lg p-4">
              <p className="mb-3 text-sm">
                {i + 1}. What does <span className="font-display font-semibold">{question.term}</span>{" "}
                mean?
              </p>
              <RadioGroup
                value={answers[question.id]}
                onValueChange={(v) => setAnswers((a) => ({ ...a, [question.id]: v }))}
              >
                {question.options.map((opt) => (
                  <label key={opt} className="flex items-center gap-2 py-1 text-sm">
                    <RadioGroupItem value={opt} />
                    {opt}
                  </label>
                ))}
              </RadioGroup>
            </div>
          ))}
          <div className="flex gap-2">
            <Button
              disabled={submit.isPending || Object.keys(answers).length === 0}
              onClick={() => submit.mutate()}
            >
              {submit.isPending ? <Spinner label="Checking…" /> : "Check answers"}
            </Button>
            <Button variant="outline" onClick={() => setTest(null)}>
              Cancel
            </Button>
          </div>
          {submit.isError && (
            <ErrorAlert
              message={submit.error instanceof Error ? submit.error.message : "Could not grade"}
            />
          )}
        </div>
      )}

      {/* ── Result ────────────────────────────────────────────────────── */}
      {result && (
        <div className="mb-6 space-y-3">
          <div className="panel rounded-lg p-6 text-center">
            <p className="font-display text-4xl font-semibold">
              {Math.round(result.score * 100)}%
            </p>
            <p className="text-sm text-muted-foreground">
              {result.correct}/{result.total} correct
            </p>
          </div>
          {result.results
            .filter((r) => !r.correct)
            .map((r) => (
              <div key={r.question_id} className="panel rounded-lg p-3 text-sm">
                <span className="font-display font-semibold">{r.term}</span> ={" "}
                <span className="text-success">{r.expected}</span>
                {r.given && (
                  <span className="text-muted-foreground"> · you said “{r.given}”</span>
                )}
              </div>
            ))}
          {result.results.some((r) => !r.correct) && (
            <div className="panel flex flex-wrap items-center gap-3 rounded-lg p-3">
              <Sparkles className="size-4 shrink-0 text-primary" />
              <p className="min-w-0 flex-1 text-sm">
                Practise the {result.results.filter((r) => !r.correct).length} you missed with
                spaced repetition.
              </p>
              <Button
                size="sm"
                variant="secondary"
                disabled={addCards.isPending || addCards.isSuccess}
                onClick={() =>
                  addCards.mutate(result.results.filter((r) => !r.correct).map((r) => r.term))
                }
              >
                {addCards.isSuccess
                  ? `Added ${addCards.data.added} to flashcards`
                  : addCards.isPending
                    ? "Adding…"
                    : "Add to flashcards"}
              </Button>
            </div>
          )}
          {addCards.isSuccess && addCards.data.added > 0 && (
            <p className="text-xs text-muted-foreground">
              Review them in Flashcards — they&apos;re due now.
            </p>
          )}
          <div className="flex gap-2">
            <Button className="gap-2" onClick={() => startTest.mutate()}>
              <RotateCcw className="size-4" />
              Test again
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setTest(null);
                setResult(null);
              }}
            >
              Back to the list
            </Button>
          </div>
        </div>
      )}

      {/* ── Browse ────────────────────────────────────────────────────── */}
      {!test && !result && data && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="relative max-w-sm flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search German, English or Roman…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <Button className="gap-2" disabled={startTest.isPending} onClick={() => startTest.mutate()}>
              <GraduationCap className="size-4" />
              {startTest.isPending ? "Preparing…" : "Test me on these"}
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              disabled={addCards.isPending}
              // Empty list = "all of them", capped server-side at 100 so a
              // 492-word import can't bury the review queue.
              onClick={() => addCards.mutate(data.entries.slice(0, 100).map((e) => e.term))}
            >
              <Sparkles className="size-4" />
              {addCards.isPending ? "Adding…" : "Add to flashcards"}
            </Button>
          </div>
          {startTest.isError && (
            <ErrorAlert
              message={
                startTest.error instanceof Error ? startTest.error.message : "Could not start"
              }
            />
          )}

          <div className="panel overflow-hidden rounded-lg">
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="w-12 px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">German</th>
                    <th className="px-3 py-2 font-medium">English</th>
                    {showUrdu && <th className="px-3 py-2 text-right font-medium">اردو</th>}
                    {showHindi && <th className="px-3 py-2 font-medium">हिन्दी</th>}
                    {showRoman && <th className="px-3 py-2 font-medium">Roman</th>}
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((e, i) => (
                    <tr
                      key={`${e.index}-${i}`}
                      className="border-b border-border/40 last:border-b-0"
                    >
                      <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                        {e.index}
                      </td>
                      <td className="px-3 py-1.5 font-medium">{e.term}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{e.gloss}</td>
                      {/* Urdu is right-to-left; without dir it renders mirrored. */}
                      {showUrdu && (
                        <td className="px-3 py-1.5 text-right" dir="rtl" lang="ur">
                          {e.urdu}
                        </td>
                      )}
                      {showHindi && (
                        <td className="px-3 py-1.5" lang="hi">
                          {e.hindi}
                        </td>
                      )}
                      {showRoman && (
                        <td className="px-3 py-1.5 text-muted-foreground">{e.roman}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.entries.length === 0 && (
              <p className="p-6 text-center text-sm text-muted-foreground">
                No entries match “{q}”.
              </p>
            )}
          </div>
        </>
      )}
    </AppShell>
  );
}
