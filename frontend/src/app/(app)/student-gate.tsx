"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { Spinner } from "@/components/shared/spinner";
import { getAccessToken, getAuthPortal, useAuthHydrated, useAuthStore } from "@/lib/auth-store";

export function StudentAppGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const portal = useAuthStore((s) => s.portal);
  const hydrated = useAuthHydrated();

  // Render the app only once the STUDENT session is the active one — pages
  // mounted before the portal switch fired their first queries with the admin
  // token (403s), and pre-hydration renders blinked through /login.
  const ready =
    hydrated && !!getAccessToken() && portal === "student" && user?.role === "student";

  useEffect(() => {
    if (!hydrated) return;
    if (!ready) {
      const token = getAccessToken();
      if (!token || getAuthPortal() !== "student" || user?.role !== "student") {
        // The admin console may hold the active slot; switch back to the saved
        // learner session instead of logging out.
        if (useAuthStore.getState().activatePortal("student")) return;
        router.replace("/login");
        return;
      }
    }
    if (user && !user.onboarded) {
      router.replace("/onboarding");
    }
  }, [router, user, hydrated, ready]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Spinner label="Loading your classroom…" />
      </div>
    );
  }
  return children;
}
