"use client";

import { Link, useRouter } from "@/components/router-link";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import { useAuthStore, getAccessToken, getAuthPortal } from "@/lib/auth-store";
import { isOpsEmail } from "@/lib/is-ops-email";
import { loginSchema } from "@/lib/validation";
import type { AuthResponse } from "@/lib/types";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { AuthMarketingPanel } from "@/components/marketing/auth-marketing-panel";
import { LearningBackdrop } from "@/components/learning-backdrop";
import { LanguageWordmarkStrip } from "@/components/marketing/language-wordmarks";

export default function LoginPage() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const user = useAuthStore((s) => s.user);
  const [email, setEmail] = useState("learner@deutschflow.ai");
  const [password, setPassword] = useState("demo12345");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const opsAccount = isOpsEmail(email);

  useEffect(() => {
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (token && user && portal === "student") {
      router.replace(user.onboarded ? "/dashboard" : "/onboarding");
    }
  }, [router, user]);

  const goToOpsLogin = () => {
    router.push(`/admin/login?email=${encodeURIComponent(email.trim())}`);
  };

  const login = useMutation({
    mutationFn: () =>
      apiFetch<AuthResponse>("/auth/login", {
        auth: false,
        method: "POST",
        json: { email, password },
      }),
    onSuccess: (res) => {
      setSession(res.access_token, res.user, "student");
      router.push(res.user.onboarded ? "/dashboard" : "/onboarding");
    },
  });

  return (
    <div className="flex min-h-screen bg-background">
      <AuthMarketingPanel />
      <div className="relative flex flex-1 flex-col items-center justify-center px-4 py-10">
      <LearningBackdrop />
      <div className="panel relative z-10 w-full max-w-md rounded-xl p-8">
        <LinguaFlowLogo className="mb-6" />
        <h1 className="font-display text-2xl font-semibold">Welcome back</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sign in to continue learning — any language, at your level (A1–C1).
        </p>
        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            const parsed = loginSchema.safeParse({ email, password });
            if (!parsed.success) {
              const errs: Record<string, string> = {};
              parsed.error.issues.forEach((err) => {
                if (err.path[0]) errs[String(err.path[0])] = err.message;
              });
              setFieldErrors(errs);
              return;
            }
            setFieldErrors({});
            if (isOpsEmail(email)) {
              goToOpsLogin();
              return;
            }
            login.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            {fieldErrors.email && <p className="text-xs text-destructive">{fieldErrors.email}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {fieldErrors.password && <p className="text-xs text-destructive">{fieldErrors.password}</p>}
          </div>
          {opsAccount && (
            <div className="rounded-lg border border-data/40 bg-data/10 px-4 py-3 text-sm">
              <p className="text-foreground">This is an Ops account. Use the admin sign-in page.</p>
              <Button type="button" variant="secondary" size="sm" className="mt-3 w-full" onClick={goToOpsLogin}>
                Continue to Ops sign-in
              </Button>
            </div>
          )}
          {login.isError && !opsAccount && (
            <ErrorAlert message={login.error instanceof Error ? login.error.message : "Login failed"} onRetry={() => login.mutate()} />
          )}
          <Button type="submit" className="w-full" disabled={login.isPending || opsAccount}>
            {login.isPending ? <Spinner label="Signing in…" /> : opsAccount ? "Use Ops sign-in above" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          No account?{" "}
          <Link to="/register" className="relative z-10 font-medium text-primary underline underline-offset-2 hover:text-primary/90">
            Register
          </Link>
          <span className="mx-2">·</span>
          <Link
            to="/admin/login"
            className="relative z-10 font-medium text-primary underline underline-offset-2 hover:text-primary/90"
          >
            Ops portal
          </Link>
        </p>
      </div>
        <div className="mt-8 w-full max-w-md lg:hidden">
          <LanguageWordmarkStrip title="Supported languages" />
        </div>
      </div>
    </div>
  );
}
