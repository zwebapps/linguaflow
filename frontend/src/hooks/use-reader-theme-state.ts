import { useEffect, useState } from "react";
import { THEME_CHANGE_EVENT } from "@/lib/theme-bridge";
import { getStoredReaderTheme, type ReaderThemeId } from "@/lib/reader-themes";

export function useReaderThemeState(): [ReaderThemeId, (id: ReaderThemeId) => void] {
  const [theme, setTheme] = useState<ReaderThemeId>(() => getStoredReaderTheme());

  useEffect(() => {
    const onChange = () => setTheme(getStoredReaderTheme());
    window.addEventListener(THEME_CHANGE_EVENT, onChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  }, []);

  return [theme, setTheme];
}
