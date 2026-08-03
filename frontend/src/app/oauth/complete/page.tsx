"use client";

/**
 * OAuth landing pad. The backend redirects here with `#token=` (success) or
 * `#error=` (anything else). The fragment never reaches a server or a log —
 * we read it, trade it for /me, store the session, and clean the URL.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "@/components/router-link";
import { Link } from "@/components/router-link";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { Spinner } from "@/components/shared/spinner";
import { ErrorAlert } from "@/components/shared/error-alert";
import { API_BASE } from "@/lib/env";
import { useAuthStore } from "@/lib/auth-store";
import type { User } from "@/lib/types";

export default function OAuthCompletePage() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const params = new URLSearchParams(window.location.hash.slice(1));
    const failure = params.get("error");
    const token = params.get("token");
    // The token must not linger in the address bar or the browser history.
    window.history.replaceState(null, "", "/oauth/complete");

    if (failure || !token) {
      setError(failure || "Sign-in didn't complete. Please try again.");
      return;
    }

    (async () => {
      try {
        const res = await fetch(`${API_BASE}/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("Your sign-in could not be confirmed.");
        const user = (await res.json()) as User;
        setSession(token, user, "student");
        router.replace(user.onboarded ? "/dashboard" : "/onboarding");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Sign-in failed.");
      }
    })();
  }, [router, setSession]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="panel w-full max-w-md space-y-4 rounded-xl p-8 text-center">
        <LinguaFlowLogo className="mx-auto" />
        {error ? (
          <>
            <ErrorAlert message={error} />
            <Link to="/login" className="text-sm text-primary underline underline-offset-4">
              Back to sign-in
            </Link>
          </>
        ) : (
          <Spinner label="Completing sign-in…" />
        )}
      </div>
    </div>
  );
}
