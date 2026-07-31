import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type VitalityPastel = "sky" | "pink" | "green" | "plum" | "khaki";

const pastelClass: Record<VitalityPastel, string> = {
  sky: "vitality-pastel-sky",
  pink: "vitality-pastel-pink",
  green: "vitality-pastel-green",
  plum: "vitality-pastel-plum",
  khaki: "vitality-pastel-khaki",
};

export function VitalityStatTile({
  label,
  value,
  hint,
  icon: Icon,
  pastel = "sky",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  pastel?: VitalityPastel;
}) {
  return (
    <div className={cn("neo-card rounded-xl p-4", pastelClass[pastel])}>
      <div className="flex items-start justify-between gap-2">
        <div className="neo-icon-well flex size-10 items-center justify-center rounded-xl">
          <Icon className="size-5" strokeWidth={1.75} aria-hidden />
        </div>
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-tight text-foreground">{value}</p>
      <p className="text-sm font-medium text-foreground/80">{label}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function VitalityDailyGoal({
  percent,
  title = "Daily goal",
  message,
  action,
}: {
  percent: number;
  title?: string;
  message: string;
  action?: ReactNode;
}) {
  const clamped = Math.min(100, Math.max(0, percent));

  return (
    <div className="neo-card flex flex-col gap-4 rounded-xl p-5 sm:flex-row sm:items-center sm:gap-6">
      <div
        className="vitality-ring relative mx-auto size-28 shrink-0 sm:mx-0"
        style={{ "--goal-pct": clamped } as CSSProperties}
        role="img"
        aria-label={`${clamped}% of ${title}`}
      >
        <span className="vitality-ring__label font-display text-2xl font-semibold">{clamped}%</span>
      </div>
      <div className="min-w-0 flex-1 text-center sm:text-left">
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <p className="font-display text-lg font-semibold text-foreground">Great progress!</p>
        <p className="mt-1 text-sm text-muted-foreground">{message}</p>
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function VitalityActivityList({
  items,
}: {
  items: { emoji: string; title: string; time: string; meta: string }[];
}) {
  return (
    <div className="neo-card rounded-xl p-4 sm:p-5">
      <h3 className="font-display text-lg font-semibold text-foreground">Today&apos;s activities</h3>
      <ul className="mt-4 space-y-3">
        {items.map((item) => (
          <li
            key={`${item.title}-${item.time}`}
            className="neo-inset flex items-center gap-3 rounded-xl px-3 py-3 transition-shadow duration-200"
          >
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-background/60 text-xl" aria-hidden>
              {item.emoji}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-foreground">{item.title}</p>
              <p className="text-xs text-muted-foreground">{item.time}</p>
            </div>
            <span className="shrink-0 text-sm font-medium text-muted-foreground">{item.meta}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
