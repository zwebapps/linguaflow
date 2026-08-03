import { cn } from "@/lib/utils";

/** Text-only wordmarks — typography like a “trusted by” strip (no trademark logo downloads). */
export type WordmarkStyle = {
  label: string;
  className: string;
  suffix?: "ericsson-bars";
};

export const PLATFORM_LANGUAGE_WORDMARKS: WordmarkStyle[] = [
  { label: "ENGLISH", className: "font-sans text-[11px] font-bold tracking-[0.2em]" },
  { label: "deutsch", className: "font-sans text-sm font-medium lowercase tracking-tight" },
  { label: "ESPAÑOL", className: "font-serif text-xs font-semibold uppercase tracking-[0.15em]" },
  { label: "Français", className: "font-sans text-xs font-medium tracking-wide" },
  { label: "العربية", className: "font-sans text-sm font-semibold" },
  { label: "中文", className: "font-sans text-sm font-bold" },
  { label: "日本語", className: "font-sans text-xs font-medium tracking-wider" },
  { label: "PORTUGUÊS", className: "font-sans text-[10px] font-bold uppercase tracking-[0.18em]" },
];

// One pin per LANGUAGE market, not per country. Saudi Arabia stands in for the
// whole Arabic-speaking region — listing UAE/Qatar/Oman beside it repeated the
// same language four times while other platform languages had no pin at all.
export const GLOBAL_MARKET_PINS = [
  { code: "USA", flag: "🇺🇸" },
  { code: "UK", flag: "🇬🇧" },
  { code: "GERMANY", flag: "🇩🇪" },
  { code: "SAUDI ARABIA", flag: "🇸🇦" },
  { code: "PAKISTAN", flag: "🇵🇰" },
] as const;

function EricssonBars() {
  return (
    <span className="ml-1 inline-flex flex-col gap-[2px] opacity-70" aria-hidden>
      <span className="h-[2px] w-3 bg-current" />
      <span className="h-[2px] w-3 bg-current opacity-75" />
      <span className="h-[2px] w-3 bg-current opacity-50" />
    </span>
  );
}

export function LanguageWordmarkStrip({
  className,
  items = PLATFORM_LANGUAGE_WORDMARKS,
  title = "Languages on LinguaFlow",
  tone = "light",
}: {
  className?: string;
  items?: WordmarkStyle[];
  title?: string;
  tone?: "light" | "dark";
}) {
  return (
    <div className={cn("space-y-3", className)}>
      <p
        className={cn(
          "text-center text-[10px] font-medium uppercase tracking-[0.25em]",
          tone === "dark" ? "text-white/45" : "text-muted-foreground",
        )}
      >
        {title}
      </p>
      <div
        className={cn(
          "flex flex-wrap items-center justify-center gap-x-6 gap-y-3 px-2",
          tone === "dark" ? "text-white/88" : "text-foreground/85",
        )}
      >
        {items.map((item) => (
          <span key={item.label} className={cn("inline-flex items-center whitespace-nowrap", item.className)}>
            {item.label}
            {item.suffix === "ericsson-bars" ? <EricssonBars /> : null}
          </span>
        ))}
      </div>
    </div>
  );
}

export function GlobalMarketPins({ className, tone = "dark" }: { className?: string; tone?: "light" | "dark" }) {
  return (
    <div className={cn("flex flex-wrap justify-center gap-2", className)}>
      {GLOBAL_MARKET_PINS.map((m) => (
        <span
          key={m.code}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide",
            tone === "dark"
              ? "border border-white/10 bg-white/5 text-white/90"
              : "border border-border bg-muted/50 text-foreground/90",
          )}
        >
          <span aria-hidden>{m.flag}</span>
          {m.code}
        </span>
      ))}
    </div>
  );
}
