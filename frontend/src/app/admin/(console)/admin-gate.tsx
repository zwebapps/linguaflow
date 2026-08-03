"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { getAccessToken, getAuthPortal, useAuthHydrated, useAuthStore } from "@/lib/auth-store";

export function AdminGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthHydrated();

  useEffect(() => {
    // Same rule as the learner gate: no redirect decisions before the
    // persisted session has rehydrated, or refreshes blink through the login.
    if (!hydrated) return;
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (!token || portal !== "admin" || user?.role !== "admin") {
      // Signing into the learner app used to clobber the admin session — if a
      // saved admin session exists, switch back to it instead of logging out.
      if (useAuthStore.getState().activatePortal("admin")) return;
      router.replace("/admin/login");
    }
  }, [router, user, hydrated]);

  return children;
}
