import { Link } from "@/components/router-link";
import { cn } from "@/lib/utils";

type LinguaFlowLogoProps = {
  variant?: "full" | "sidebar" | "mark";
  className?: string;
  /** When set, wraps the logo in a link (e.g. home / dashboard). */
  to?: string;
};

function Wordmark({ compact }: { compact?: boolean }) {
  return (
    <span
      className={cn(
        "font-display font-semibold tracking-tight text-foreground",
        compact ? "text-lg leading-none" : "text-2xl leading-none",
      )}
    >
      Lingua<span className="text-primary">Flow</span>
    </span>
  );
}

export function LinguaFlowLogo({ variant = "full", className, to }: LinguaFlowLogoProps) {
  const inner =
    variant === "mark" ? (
      <div
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground shadow-sm ring-1 ring-border/40",
          className,
        )}
        aria-hidden
      >
        LF
      </div>
    ) : (
      <div className={cn(variant === "sidebar" ? "max-w-[168px]" : "mx-auto max-w-[240px]", className)}>
        <Wordmark compact={variant === "sidebar"} />
        {variant === "full" && (
          <p className="mt-1.5 text-center text-xs text-muted-foreground">Learn any language, your way</p>
        )}
      </div>
    );

  const labeled = (
    <span className="inline-flex shrink-0" aria-label="LinguaFlow">
      {inner}
    </span>
  );

  if (to) {
    return (
      <Link to={to} className="inline-flex shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {labeled}
      </Link>
    );
  }

  return labeled;
}
