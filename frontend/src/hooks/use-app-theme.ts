import { useEffect, useState } from "react";
import { getStoredAppTheme, type AppThemeId } from "@/lib/app-themes";
import { THEME_CHANGE_EVENT } from "@/lib/theme-bridge";

export function useAppThemeId(): AppThemeId {
  // Two-phase like useStoredState, NOT a localStorage-reading initializer:
  // the server always renders "classroom", so a Midnight/Study user got a
  // server/client className mismatch in AppShell → React regenerated the
  // whole tree on every hard refresh, which flashed an empty (black, on
  // Midnight) canvas. Default first, adopt the stored theme after mount —
  // the html[data-app-theme] boot script already paints the right colors
  // pre-hydration, so only conditional classes settle a frame later.
  const [theme, setTheme] = useState<AppThemeId>("classroom");

  useEffect(() => {
    setTheme(getStoredAppTheme());
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<AppThemeId>).detail;
      if (detail) setTheme(detail);
      else setTheme(getStoredAppTheme());
    };
    window.addEventListener(THEME_CHANGE_EVENT, onChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  }, []);

  return theme;
}
