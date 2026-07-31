import { Check } from "lucide-react";
import {
  readerThemes,
  setStoredReaderTheme,
  type ReaderThemeId,
} from "@/lib/reader-themes";

export function ReaderThemePicker({
  value,
  onChange,
  compact = false,
}: {
  value: ReaderThemeId;
  onChange: (id: ReaderThemeId) => void;
  compact?: boolean;
}) {
  return (
    <div className="grid gap-2">
      {readerThemes.map((t) => {
        const active = value === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setStoredReaderTheme(t.id);
              onChange(t.id);
            }}
            className={`flex items-start gap-3 rounded-md border px-3 py-2.5 text-left text-sm transition-colors ${
              active
                ? "amber-glow border-amber-500/50 bg-amber-500/10"
                : "border-border hover:bg-secondary/50"
            }`}
          >
            <span
              className="mt-0.5 size-5 shrink-0 rounded-full border border-border"
              style={{ backgroundColor: t.swatch }}
              aria-hidden
            />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 font-medium">
                {compact ? t.shortLabel : t.label}
                {active && <Check className="size-3.5 text-amber-500" aria-hidden />}
              </span>
              {!compact && <span className="mt-0.5 block text-xs text-muted-foreground">{t.description}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
