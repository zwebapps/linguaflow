"use client";

import { Link } from "@/components/router-link";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { CefrBadge } from "@/components/shared/cefr-badge";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { TopicSelect } from "@/components/learner/topic-select";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { quizCountSchema } from "@/lib/validation";
import type { QuizGenerateResponse, QuizSubmitResponse } from "@/lib/types";

export default function QuizPage() {
  // The quiz runs at the level the learner set in their profile — the page
  // used to hardcode A2, which quizzed A1 and C1 learners alike at A2.
  const level = useAuthStore((s) => s.user)?.cefr_level ?? "A1";
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(5);
  const [quiz, setQuiz] = useState<QuizGenerateResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QuizSubmitResponse | null>(null);

  const generate = useMutation({
    mutationFn: () =>
      apiFetch<QuizGenerateResponse>("/quiz/generate", {
        method: "POST",
        json: { topic, cefr_level: level, n: count, document_id: null },
      }),
    onSuccess: (q) => {
      setQuiz(q);
      setResult(null);
      setAnswers({});
    },
  });

  const submit = useMutation({
    mutationFn: () =>
      apiFetch<QuizSubmitResponse>("/quiz/submit", {
        method: "POST",
        json: {
          quiz_id: quiz!.quiz_id,
          answers: quiz!.questions.map((q) => ({
            question_id: q.id,
            value: answers[q.id] ?? "",
          })),
        },
      }),
    onSuccess: setResult,
  });

  return (
    <AppShell title="Quiz" subtitle="Generate and grade MCQ / cloze exercises">
      {!quiz && (
        <div className="panel max-w-lg space-y-4 rounded-lg p-6">
          <div className="flex items-center justify-between">
            <Label>Your level</Label>
            <div className="flex items-center gap-2">
              <CefrBadge level={level} />
              <span className="text-xs text-muted-foreground">change it in Settings</span>
            </div>
          </div>
          <div className="space-y-2">
            <Label>Topic</Label>
            <TopicSelect level={level} value={topic} onChange={setTopic} />
          </div>
          <div className="space-y-2">
            <Label>Questions</Label>
            <Input type="number" value={count} onChange={(e) => setCount(Number(e.target.value))} />
          </div>
          {generate.isError && (
            <ErrorAlert message={generate.error.message} onRetry={() => generate.mutate()} />
          )}
          <Button
            disabled={!topic.trim() || !quizCountSchema.safeParse(count).success || generate.isPending}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? <Spinner label="Generating…" /> : "Generate quiz"}
          </Button>
        </div>
      )}

      {quiz && !result && (
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <h2 className="font-display text-xl font-semibold">{quiz.topic}</h2>
            <CefrBadge level={quiz.cefr_level} />
          </div>
          {quiz.questions.map((q, i) => (
            <div key={q.id} className="panel rounded-lg p-4">
              <p className="mb-3 text-sm">
                {i + 1}. {q.prompt}
              </p>
              {q.type === "mcq" && q.options ? (
                <RadioGroup
                  value={answers[q.id]}
                  onValueChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))}
                >
                  {q.options.map((opt) => (
                    <label key={opt} className="flex items-center gap-2 py-1 text-sm">
                      <RadioGroupItem value={opt} />
                      {opt}
                    </label>
                  ))}
                </RadioGroup>
              ) : (
                <Input
                  value={answers[q.id] ?? ""}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                />
              )}
            </div>
          ))}
          <Button onClick={() => submit.mutate()} disabled={submit.isPending}>
            {submit.isPending ? <Spinner label="Submitting…" /> : "Submit answers"}
          </Button>
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <div className="panel rounded-lg p-6 text-center">
            <p className="font-display text-4xl font-semibold">{Math.round(result.score * 100)}%</p>
            <p className="text-sm text-muted-foreground">
              {result.correct}/{result.total} correct · estimate {result.cefr_estimate}
            </p>
          </div>
          {result.results.map((r) => (
            <div key={r.question_id} className="panel rounded-lg p-4 text-sm">
              <p className={r.correct ? "text-success" : "text-destructive"}>
                {r.correct ? "✓" : "✗"} Expected: {r.expected} · Given: {r.given}
              </p>
              <p className="mt-1 text-muted-foreground">{r.explanation}</p>
            </div>
          ))}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => { setQuiz(null); setResult(null); }}>
              Retry
            </Button>
            <Button asChild>
              <Link to="/tutor">Ask the tutor about my mistakes</Link>
            </Button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
