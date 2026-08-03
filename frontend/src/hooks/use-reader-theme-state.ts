import { useEffect } from "react";
import { THEME_CHANGE_EVENT } from "@/lib/theme-bridge";
import { getStoredReaderTheme, READER_FONT_SIZE_KEY, type ReaderThemeId } from "@/lib/reader-themes";
import { useStoredState } from "@/hooks/use-stored-state";

export function useReaderThemeState(): [ReaderThemeId, (id: ReaderThemeId) => void] {
  // Via useStoredState, NOT a localStorage-reading initializer: the server
  // renders the default and a customised client rendered the preference, which
  // is a hydration mismatch on every load for anyone who changed the theme.
  const [theme, setTheme] = useStoredState<ReaderThemeId>(getStoredReaderTheme, "reader-sepia");

  useEffect(() => {
    const onChange = () => setTheme(getStoredReaderTheme());
    window.addEventListener(THEME_CHANGE_EVENT, onChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  }, [setTheme]);

  return [theme, setTheme];
}

export const DEFAULT_READER_FONT_SIZE = 19;

/** Persisted reader font size — same hydration-safe two-phase pattern. */
export function useReaderFontSize(): [number, (px: number) => void] {
  const [size, setSize] = useStoredState<number>(
    () => Number(localStorage.getItem(READER_FONT_SIZE_KEY) ?? DEFAULT_READER_FONT_SIZE),
    DEFAULT_READER_FONT_SIZE,
  );
  return [size, setSize];
}
