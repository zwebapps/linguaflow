import { syncReaderThemeWithApp, dispatchThemeChange } from "./theme-bridge";

export type AppThemeId = "classroom" | "obsidian" | "study";

export const APP_THEME_STORAGE_KEY = "df-app-theme";

export const appThemes = [
  {
    id: "classroom" as const,
    label: "Vitality",
    description: "Soft pastels · evolved neumorphism · wellness-style clarity",
    swatch: "#eef2f8",
    accent: "#5b8fc7",
  },
  {
    id: "obsidian" as const,
    label: "Midnight",
    description: "Midnight Cyber · low light · matches the dashboard",
    swatch: "#0B0F19",
    accent: "#f59e0b",
  },
  {
    id: "study" as const,
    label: "Forest",
    description: "Forest Sanctuary · calm focus · grammar & quizzes",
    swatch: "#dff5eb",
    accent: "#059669",
  },
] satisfies ReadonlyArray<{
  id: AppThemeId;
  label: string;
  description: string;
  swatch: string;
  accent: string;
}>;

export function getStoredAppTheme(): AppThemeId {
  if (typeof localStorage === "undefined") return "classroom";
  const stored = localStorage.getItem(APP_THEME_STORAGE_KEY);
  if (stored === "classroom" || stored === "obsidian" || stored === "study") return stored;
  return "classroom";
}

export function applyAppTheme(id: AppThemeId) {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.appTheme = id;
  }
  localStorage.setItem(APP_THEME_STORAGE_KEY, id);
  syncReaderThemeWithApp(id);
  dispatchThemeChange(id);
}

export function initAppTheme() {
  const id = getStoredAppTheme();
  if (typeof document !== "undefined") {
    document.documentElement.dataset.appTheme = id;
  }
}
