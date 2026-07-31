"use client";

import { useRouter } from "@/components/router-link";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";
import { getAccessToken, useAuthStore } from "@/lib/auth-store";
import { onboardingSchema } from "@/lib/validation";
import type { User } from "@/lib/types";
import { ErrorAlert } from "@/components/shared/error-alert";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";

const steps = ["goal", "cefr_level", "learning_style", "daily_goal_minutes"] as const;

export default function OnboardingPage() {
  const router = useRouter();
  const setUser = useAuthStore((s) => s.setUser);
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    goal: "travel" as const,
    cefr_level: "A2" as const,
    learning_style: "balanced" as const,
    daily_goal_minutes: 20,
  });

  useEffect(() => {
    if (!getAccessToken()) router.replace("/login");
  }, [router]);

  const save = useMutation({
    mutationFn: () => apiFetch<User>("/me", { method: "PATCH", json: form }),
    onSuccess: (user) => {
      setUser(user);
      router.push("/tutor");
    },
  });

  const progress = ((step + 1) / steps.length) * 100;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel w-full max-w-lg rounded-xl p-8">
        <LinguaFlowLogo className="mb-6 max-w-[200px]" />
        <h1 className="font-display text-2xl font-semibold">Welcome</h1>
        <Progress value={progress} className="mt-4 h-2" />
        <p className="label-mono mt-2">
          Step {step + 1} of {steps.length}
        </p>

        <div className="mt-6 space-y-4">
          {step === 0 && (
            <div className="space-y-2">
              <Label>Learning goal</Label>
              <Select value={form.goal} onValueChange={(v) => setForm((f) => ({ ...f, goal: v as typeof form.goal }))}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["travel", "work", "study", "heritage", "exam"].map((g) => (
                    <SelectItem key={g} value={g}>
                      {g}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {step === 1 && (
            <div className="space-y-2">
              <Label>CEFR level</Label>
              <Select
                value={form.cefr_level}
                onValueChange={(v) => setForm((f) => ({ ...f, cefr_level: v as typeof form.cefr_level }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["A1", "A2", "B1", "B2", "C1"].map((l) => (
                    <SelectItem key={l} value={l}>
                      {l}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {step === 2 && (
            <div className="space-y-2">
              <Label>Learning style</Label>
              <Select
                value={form.learning_style}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, learning_style: v as typeof form.learning_style }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["visual", "balanced", "conversation"].map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {step === 3 && (
            <div className="space-y-2">
              <Label>Daily goal (minutes)</Label>
              <Select
                value={String(form.daily_goal_minutes)}
                onValueChange={(v) => setForm((f) => ({ ...f, daily_goal_minutes: Number(v) }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[10, 15, 20, 30, 45, 60].map((m) => (
                    <SelectItem key={m} value={String(m)}>
                      {m} min
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {save.isError && (
          <div className="mt-4">
            <ErrorAlert
              message={save.error instanceof Error ? save.error.message : "Could not save"}
              onRetry={() => save.mutate()}
            />
          </div>
        )}

        <div className="mt-8 flex justify-between gap-2">
          <Button variant="outline" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            Back
          </Button>
          {step < steps.length - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)}>Continue</Button>
          ) : (
            <Button
              onClick={() => {
                if (onboardingSchema.safeParse(form).success) save.mutate();
              }}
              disabled={save.isPending}
            >
              Finish
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
