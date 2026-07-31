import { useEffect, useState } from "react";
import { getStoredAppTheme, type AppThemeId } from "@/lib/app-themes";
import { THEME_CHANGE_EVENT } from "@/lib/theme-bridge";

export function useAppThemeId(): AppThemeId {
  const [theme, setTheme] = useState<AppThemeId>(() => getStoredAppTheme());

  useEffect(() => {
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
