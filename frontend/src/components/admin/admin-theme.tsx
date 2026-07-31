"use client";

import { useEffect, type ReactNode } from "react";
import { getStoredAppTheme } from "@/lib/app-themes";

/** Ops console always uses Midnight tokens; restore learner theme when leaving /admin. */
export function AdminTheme({ children }: { children: ReactNode }) {
  useEffect(() => {
    const root = document.documentElement;
    const previous = getStoredAppTheme();
    root.dataset.appTheme = "obsidian";
    root.style.colorScheme = "dark";

    return () => {
      root.dataset.appTheme = previous;
      root.style.colorScheme = previous === "obsidian" ? "dark" : "light";
    };
  }, []);

  return children;
}
