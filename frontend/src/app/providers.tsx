"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { initAppTheme } from "@/lib/app-themes";
import { USE_MOCKS } from "@/lib/env";

if (typeof document !== "undefined") {
  initAppTheme();
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient());

  useEffect(() => {
    if (USE_MOCKS && process.env.NODE_ENV === "development") {
      void import("@/mocks/browser").then((m) => m.startMockWorker());
    }
  }, []);

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster richColors position="top-center" />
    </QueryClientProvider>
  );
}
