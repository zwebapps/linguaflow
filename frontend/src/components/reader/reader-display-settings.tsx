import { useEffect, useState } from "react";
import { ChevronDown, SlidersHorizontal, Type } from "lucide-react";
import { ReaderThemePicker } from "@/components/reader/reader-theme-picker";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import {
  READER_FONT_SIZE_KEY,
  readerThemes,
  setStoredReaderTheme,
  type ReaderThemeId,
} from "@/lib/reader-themes";
import { cn } from "@/lib/utils";

function persistSize(px: number) {
  localStorage.setItem(READER_FONT_SIZE_KEY, String(px));
}

function ThemeSizeControls({
  theme,
  onThemeChange,
  size,
  onSizeChange,
}: {
  theme: ReaderThemeId;
  onThemeChange: (id: ReaderThemeId) => void;
  size: number;
  onSizeChange: (px: number) => void;
}) {
  return (
    <div className="space-y-5">
      <div className="flex gap-2 overflow-x-auto pb-1 lg:hidden">
        {readerThemes.map((t) => {
          const active = theme === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setStoredReaderTheme(t.id);
                onThemeChange(t.id);
              }}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                active ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground",
              )}
            >
              <span className="size-3 rounded-full border border-border" style={{ backgroundColor: t.swatch }} />
              {t.shortLabel}
            </button>
          );
        })}
      </div>
      <div className="hidden lg:block">
        <p className="label-mono mb-2">Reading theme</p>
        <ReaderThemePicker value={theme} onChange={onThemeChange} />
      </div>
      <div className="lg:hidden">
        <p className="label-mono mb-2">Reading theme</p>
        <ReaderThemePicker value={theme} onChange={onThemeChange} compact />
      </div>
      <div className="space-y-2">
        <p className="label-mono flex items-center gap-1.5">
          <Type className="size-3" aria-hidden />
          Text size · {size}px
        </p>
        <Slider
          value={[size]}
          min={15}
          max={26}
          step={1}
          onValueChange={(v) => {
            onSizeChange(v[0]);
            persistSize(v[0]);
          }}
        />
      </div>
    </div>
  );
}

export function ReaderDisplaySettings({
  theme,
  onThemeChange,
  size,
  onSizeChange,
  className,
}: {
  theme: ReaderThemeId;
  onThemeChange: (id: ReaderThemeId) => void;
  size: number;
  onSizeChange: (px: number) => void;
  className?: string;
}) {
  const activeTheme = readerThemes.find((t) => t.id === theme);
  const summary = `${activeTheme?.shortLabel ?? "Theme"} · ${size}px`;
  const [sheetOpen, setSheetOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(true);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setDesktopOpen(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  return (
    <div className={cn(className)}>
      {/* Mobile: bottom sheet — keeps reading area full width */}
      <div className="lg:hidden">
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" className="h-auto w-full justify-between gap-2 py-3">
              <span className="flex items-center gap-2 text-sm font-medium">
                <SlidersHorizontal className="size-4 text-primary" aria-hidden />
                Reading display
              </span>
              <span className="truncate text-xs text-muted-foreground">{summary}</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="bottom" className="max-h-[min(85vh,520px)] rounded-t-2xl">
            <SheetHeader className="text-left">
              <SheetTitle className="font-display text-lg">Reading display</SheetTitle>
            </SheetHeader>
            <div className="mt-4 overflow-y-auto pb-6">
              <ThemeSizeControls
                theme={theme}
                onThemeChange={onThemeChange}
                size={size}
                onSizeChange={onSizeChange}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {/* Desktop: collapsible panel in sidebar */}
      <Collapsible open={desktopOpen} onOpenChange={setDesktopOpen} className="hidden lg:block">
        <div className="panel overflow-hidden rounded-lg">
          <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-secondary/30">
            <SlidersHorizontal className="size-4 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">Reading display</span>
              <span className="block truncate text-xs text-muted-foreground">{summary}</span>
            </span>
            <ChevronDown
              className={cn("size-4 shrink-0 text-muted-foreground transition-transform", desktopOpen && "rotate-180")}
              aria-hidden
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="border-t border-border px-4 pb-4 pt-3">
            <ThemeSizeControls
              theme={theme}
              onThemeChange={onThemeChange}
              size={size}
              onSizeChange={onSizeChange}
            />
          </CollapsibleContent>
        </div>
      </Collapsible>
    </div>
  );
}
