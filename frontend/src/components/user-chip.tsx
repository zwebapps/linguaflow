"use client";

/** Topbar identity chip: gradient initials + name, linking to settings. */

import { Link } from "@/components/router-link";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

function initials(name?: string | null, email?: string | null): string {
  const source = (name || "").trim() || (email || "").split("@")[0];
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  const chars = (parts.length >= 2 ? parts[0][0] + parts[1][0] : source.slice(0, 2)) || "?";
  return chars.toUpperCase();
}

export function UserChip({
  href = "/settings",
  className,
}: {
  /** null renders a non-interactive chip (surfaces with no account page). */
  href?: string | null;
  className?: string;
}) {
  const user = useAuthStore((s) => s.user);

  const chipClass = cn(
    "group flex items-center gap-2.5 rounded-full border border-border/70 bg-card/70 py-1 pl-1 pr-3 transition-colors",
    href && "hover:border-primary/40 hover:bg-card",
    className,
  );
  const body = (
    <>
      <span
        aria-hidden
        suppressHydrationWarning
        className="flex size-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-primary/60 font-display text-[11px] font-semibold text-primary-foreground shadow-sm"
      >
        {initials(user?.display_name, user?.email)}
      </span>
      <span
        suppressHydrationWarning
        className="hidden max-w-[10rem] truncate text-sm font-medium sm:block"
      >
        {user?.display_name || user?.email || "Account"}
      </span>
    </>
  );

  if (!href) {
    return <span className={chipClass}>{body}</span>;
  }
  return (
    <Link to={href} className={chipClass} aria-label="Your account">
      {body}
    </Link>
  );
}
