"use client";

import { useEffect } from "react";
import { useRouter } from "@/components/router-link";
import { getAccessToken, getAuthPortal, useAuthStore } from "@/lib/auth-store";

export function AdminGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    const token = getAccessToken();
    const portal = getAuthPortal();
    if (!token || portal !== "admin" || user?.role !== "admin") {
      router.replace("/admin/login");
    }
  }, [router, user]);

  return children;
}
