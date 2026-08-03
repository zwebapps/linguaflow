import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { GlobalMarketPins, LanguageWordmarkStrip } from "@/components/marketing/language-wordmarks";
import { cn } from "@/lib/utils";

export function AuthMarketingPanel({ className }: { className?: string }) {
  return (
    <aside
      className={cn(
        "relative hidden flex-1 flex-col justify-between overflow-hidden border-r border-border/40 bg-[#0a0e17] px-8 py-10 text-foreground lg:flex",
        className,
      )}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        aria-hidden
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 40%, oklch(0.45 0.08 240 / 0.35), transparent 70%)",
        }}
      />
      <div className="relative z-10">
        <div className="text-white [&_span]:text-white [&_.text-primary]:text-amber-400">
          <LinguaFlowLogo variant="sidebar" />
        </div>
        <p className="mt-8 max-w-md font-display text-3xl font-semibold leading-tight text-white">
          Learn across continents
        </p>
        <p className="mt-3 max-w-sm text-sm text-white/65">
          One platform for guided reading, AI tutoring, speaking practice, and progress tracking — at CEFR
          levels A1–C1.
        </p>
      </div>

      <div className="relative z-10 space-y-8">
        <div className="mx-auto flex h-40 w-40 items-center justify-center rounded-full border border-amber-500/20 bg-[radial-gradient(circle_at_30%_30%,#1a2744,#050810)] shadow-[0_0_60px_oklch(0.55_0.12_85_/_0.15)]">
          <span className="text-5xl opacity-90" aria-hidden>
            🌍
          </span>
        </div>
        <GlobalMarketPins />
        <LanguageWordmarkStrip title="Supported languages" tone="dark" />
      </div>
    </aside>
  );
}
