"use client";

import { Link, useRouter, useSearchParams } from "@/components/router-link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { loginSchema } from "@/lib/validation";
import type { AuthResponse } from "@/lib/types";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";

export function AdminLoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailFromSearch = searchParams.get("email") ?? undefined;
  const setSession = useAuthStore((s) => s.setSession);
  const [email, setEmail] = useState(emailFromSearch ?? "admin@linguaflow.dev");
  const [password, setPassword] = useState("changeme123");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const login = useMutation({
    mutationFn: async () => {
      const res = await apiFetch<AuthResponse>("/auth/login", {
        auth: false,
        method: "POST",
        json: { email, password },
      });
      if (res.user.role !== "admin") {
        throw new Error("This account is not an admin. Use learner sign-in at /login.");
      }
      return res;
    },
    onSuccess: (res) => {
      setSession(res.access_token, res.user, "admin");
      router.push("/admin/knowledge-base");
    },
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel w-full max-w-md rounded-xl border border-border bg-card p-8 shadow-xl">
        <LinguaFlowLogo className="mb-6" />
        <h1 className="font-display text-2xl font-semibold">Ops sign-in</h1>
        <p className="mt-1 text-sm text-muted-foreground">Ingestion, models, usage — not the learner app</p>
        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            const parsed = loginSchema.safeParse({ email, password });
            if (!parsed.success) {
              const errs: Record<string, string> = {};
              for (const err of parsed.error.issues) {
                if (err.path[0]) errs[String(err.path[0])] = err.message;
              }
              setFieldErrors(errs);
              return;
            }
            setFieldErrors({});
            login.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="ops-email">Ops email</Label>
            <Input id="ops-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            {fieldErrors.email && <p className="text-xs text-destructive">{fieldErrors.email}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="ops-password">Password</Label>
            <Input id="ops-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {fieldErrors.password && <p className="text-xs text-destructive">{fieldErrors.password}</p>}
          </div>
          {login.isError && (
            <ErrorAlert message={login.error instanceof Error ? login.error.message : "Sign-in failed"} onRetry={() => login.mutate()} />
          )}
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {login.isPending ? <Spinner label="Signing in…" /> : "Enter ops console"}
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          <Link to="/login" className="hover:underline">← Learner sign-in</Link>
        </p>
      </div>
    </div>
  );
}
