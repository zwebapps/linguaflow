"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { Spinner } from "@/components/shared/spinner";
import { getAccessToken, getAuthPortal, useAuthHydrated, useAuthStore } from "@/lib/auth-store";

export function AdminGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const portal = useAuthStore((s) => s.portal);
  const hydrated = useAuthHydrated();

  // The console renders ONLY once the admin session is the ACTIVE one.
  // Rendering children early made their first API calls fire with the learner
  // portal's token — every admin query opened with a 403.
  const ready = hydrated && !!getAccessToken() && portal === "admin" && user?.role === "admin";

  useEffect(() => {
    // Never decide before the persisted session has rehydrated, or refreshes
    // blink through the login.
    if (!hydrated || ready) return;
    const token = getAccessToken();
    if (!token || getAuthPortal() !== "admin" || user?.role !== "admin") {
      // Signing into the learner app used to clobber the admin session — if a
      // saved admin session exists, switch back to it instead of logging out.
      if (useAuthStore.getState().activatePortal("admin")) return;
      router.replace("/admin/login");
    }
  }, [router, user, hydrated, ready]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Spinner label="Opening the console…" />
      </div>
    );
  }
  return children;
}
