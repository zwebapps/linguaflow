import type { AppThemeId } from "@/lib/app-themes";
import { setStoredReaderTheme, type ReaderThemeId } from "@/lib/reader-themes";

export const APP_TO_READER_THEME: Record<AppThemeId, ReaderThemeId> = {
  classroom: "reader-sepia",
  obsidian: "reader-midnight",
  study: "reader-forest",
};

export const THEME_CHANGE_EVENT = "df-theme-change";

export function syncReaderThemeWithApp(appTheme: AppThemeId) {
  setStoredReaderTheme(APP_TO_READER_THEME[appTheme]);
}

export function dispatchThemeChange(appTheme: AppThemeId) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: appTheme }));
  }
}
