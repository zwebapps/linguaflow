export type ReaderThemeId = "reader-sepia" | "reader-midnight" | "reader-forest";

export const READER_THEME_STORAGE_KEY = "df-reader-theme";
export const READER_FONT_SIZE_KEY = "df-reader-size";

export const readerThemes = [
  {
    id: "reader-sepia" as const,
    label: "Amber Sepia",
    shortLabel: "Sepia",
    description: "Long-form reading · reduced eye strain",
    swatch: "#F7F1E3",
  },
  {
    id: "reader-midnight" as const,
    label: "Midnight Cyber",
    shortLabel: "Midnight",
    description: "Low light · matches the dashboard",
    swatch: "#0B0F19",
  },
  {
    id: "reader-forest" as const,
    label: "Forest Sanctuary",
    shortLabel: "Forest",
    description: "Calm focus · grammar & quizzes",
    swatch: "#dff5eb",
  },
] satisfies ReadonlyArray<{
  id: ReaderThemeId;
  label: string;
  shortLabel: string;
  description: string;
  swatch: string;
}>;

export function getStoredReaderTheme(): ReaderThemeId {
  if (typeof localStorage === "undefined") return "reader-sepia";
  const stored = localStorage.getItem(READER_THEME_STORAGE_KEY);
  if (stored === "reader-midnight" || stored === "reader-forest" || stored === "reader-sepia") {
    return stored;
  }
  return "reader-sepia";
}

export function setStoredReaderTheme(id: ReaderThemeId) {
  localStorage.setItem(READER_THEME_STORAGE_KEY, id);
}
