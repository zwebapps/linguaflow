import { useState } from "react";
import { Check } from "lucide-react";
import {
  appThemes,
  applyAppTheme,
  getStoredAppTheme,
  type AppThemeId,
} from "@/lib/app-themes";
import { cn } from "@/lib/utils";

/** Sidebar appearance control — sits above the signed-in user block. */
export function LearnerThemeSwitcher() {
  const [theme, setTheme] = useState<AppThemeId>(() => getStoredAppTheme());

  return (
    <div className="border-t border-sidebar-border px-4 py-3">
      <p className="label-mono mb-2.5">Theme</p>
      <div
        className="flex rounded-lg border border-border bg-background/50 p-0.5"
        role="group"
        aria-label="Choose app theme"
      >
        {appThemes.map((t) => {
          const active = theme === t.id;
          return (
            <button
              key={t.id}
              type="button"
              title={t.description}
              aria-pressed={active}
              onClick={() => {
                applyAppTheme(t.id);
                setTheme(t.id);
              }}
              className={cn(
                "relative flex flex-1 flex-col items-center gap-1 rounded-md px-1 py-2 text-[10px] font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-sidebar-accent/40 hover:text-foreground",
              )}
            >
              <span
                className="size-4 rounded-full border border-border shadow-inner"
                style={{ backgroundColor: t.swatch, boxShadow: `inset 0 0 0 2px ${t.accent}33` }}
                aria-hidden
              />
              <span className="flex items-center gap-0.5">
                {t.label}
                {active && <Check className="size-2.5 text-primary" aria-hidden />}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
