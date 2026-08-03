"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { getAccessToken, getAuthPortal, useAuthHydrated, useAuthStore } from "@/lib/auth-store";

export function StudentAppGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthHydrated();

  useEffect(() => {
    // Never decide before the persisted session has loaded — deciding early is
    // what blinked logged-in users through /login on every hard refresh.
    if (!hydrated) return;
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (!token || portal !== "student" || user?.role !== "student") {
      // The admin console may hold the active slot; switch back to the saved
      // learner session instead of logging out.
      if (useAuthStore.getState().activatePortal("student")) return;
      router.replace("/login");
      return;
    }
    if (user && !user.onboarded) {
      router.replace("/onboarding");
    }
  }, [router, user, hydrated]);

  return children;
}
