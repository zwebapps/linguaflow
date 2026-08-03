"use client";

/** Where the emailed verification link lands: POSTs the ?token and reports. */

import { useEffect, useRef, useState } from "react";
import { Link } from "@/components/router-link";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { Spinner } from "@/components/shared/spinner";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

type State = { status: "working" } | { status: "done"; email: string } | { status: "failed"; message: string };

export default function VerifyEmailPage() {
  const [state, setState] = useState<State>({ status: "working" });
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setState({ status: "failed", message: "This link is missing its token — use the full link from the email." });
      return;
    }
    (async () => {
      try {
        const res = await apiFetch<{ verified: boolean; email: string }>("/auth/verify-email", {
          auth: false,
          method: "POST",
          json: { token },
        });
        setState({ status: "done", email: res.email });
        // Clear the banner immediately when the verified account is signed in here.
        if (user && user.email === res.email) setUser({ ...user, email_verified: true });
      } catch (e) {
        setState({
          status: "failed",
          message: e instanceof Error ? e.message : "Verification failed.",
        });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel w-full max-w-md space-y-4 rounded-xl p-8 text-center">
        <LinguaFlowLogo className="mx-auto" />
        {state.status === "working" && <Spinner label="Verifying your email…" />}
        {state.status === "done" && (
          <>
            <p className="text-2xl" aria-hidden>
              ✅
            </p>
            <h1 className="font-display text-xl font-semibold">Email verified</h1>
            <p className="text-sm text-muted-foreground">
              {state.email} is confirmed. Viel Erfolg beim Lernen!
            </p>
            <Link to="/dashboard" className="text-sm text-primary underline underline-offset-4">
              Go to your dashboard
            </Link>
          </>
        )}
        {state.status === "failed" && (
          <>
            <h1 className="font-display text-xl font-semibold">That link didn&apos;t work</h1>
            <p className="text-sm text-muted-foreground">{state.message}</p>
            <p className="text-sm text-muted-foreground">
              Sign in and use <span className="font-medium">Resend verification email</span> to get a fresh link.
            </p>
            <Link to="/login" className="text-sm text-primary underline underline-offset-4">
              Back to sign-in
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
