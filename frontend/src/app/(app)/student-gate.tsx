"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { getAccessToken, getAuthPortal, useAuthStore } from "@/lib/auth-store";

export function StudentAppGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (!token || portal !== "student" || user?.role !== "student") {
      router.replace("/login");
      return;
    }
    if (user && !user.onboarded) {
      router.replace("/onboarding");
    }
  }, [router, user]);

  return children;
}
