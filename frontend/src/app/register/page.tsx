"use client";

import { Link, useRouter } from "@/components/router-link";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import { getAccessToken, getAuthPortal, useAuthStore } from "@/lib/auth-store";
import { registerSchema } from "@/lib/validation";
import type { AuthResponse } from "@/lib/types";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";

export default function RegisterPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const setSession = useAuthStore((s) => s.setSession);
  const [form, setForm] = useState({ email: "", password: "", display_name: "" });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (token && user && portal === "student") {
      router.replace(user.onboarded ? "/dashboard" : "/onboarding");
    }
  }, [router, user]);

  const register = useMutation({
    mutationFn: () =>
      apiFetch<AuthResponse>("/auth/register", { auth: false, method: "POST", json: form }),
    onSuccess: (res) => {
      setSession(res.access_token, res.user, "student");
      router.push("/onboarding");
    },
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel w-full max-w-md rounded-xl p-8">
        <LinguaFlowLogo className="mb-6" />
        <h1 className="font-display text-2xl font-semibold">Create account</h1>
        <p className="mt-1 text-sm text-muted-foreground">Join LinguaFlow — one account for your language journey.</p>
        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            const parsed = registerSchema.safeParse(form);
            if (!parsed.success) {
              const errs: Record<string, string> = {};
              parsed.error.issues.forEach((err) => {
                if (err.path[0]) errs[String(err.path[0])] = err.message;
              });
              setFieldErrors(errs);
              return;
            }
            setFieldErrors({});
            register.mutate();
          }}
        >
          {(["display_name", "email", "password"] as const).map((key) => (
            <div key={key} className="space-y-2">
              <Label htmlFor={key}>{key.replace("_", " ")}</Label>
              <Input
                id={key}
                type={key === "password" ? "password" : key === "email" ? "email" : "text"}
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
              />
              {fieldErrors[key] && <p className="text-xs text-destructive">{fieldErrors[key]}</p>}
            </div>
          ))}
          {register.isError && (
            <ErrorAlert
              message={register.error instanceof Error ? register.error.message : "Registration failed"}
              onRetry={() => register.mutate()}
            />
          )}
          <Button type="submit" className="w-full" disabled={register.isPending}>
            {register.isPending ? <Spinner label="Creating…" /> : "Register"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link to="/login" className="text-data hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
