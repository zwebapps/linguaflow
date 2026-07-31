import type { ReactNode } from "react";
import { BookOpen, ClipboardList, PenLine } from "lucide-react";
import { cn } from "@/lib/utils";

type ActivityKind = "reading" | "vocabulary" | "writing";

const meta: Record<
  ActivityKind,
  { title: string; icon: typeof BookOpen; hint: string }
> = {
  reading: {
    title: "Reading",
    icon: BookOpen,
    hint: "Long-form text · illustration + questions layout",
  },
  vocabulary: {
    title: "Vocabulary",
    icon: ClipboardList,
    hint: "Day sets · learn · speak · write · use",
  },
  writing: {
    title: "Writing pad",
    icon: PenLine,
    hint: "Prompt · lined answer area · feedback",
  },
};

/** Concept header only — no reference artwork as background. */
export function ActivityIntro({
  kind,
  subtitle,
  className,
  children,
}: {
  kind: ActivityKind;
  subtitle: string;
  className?: string;
  children?: ReactNode;
}) {
  const { title, icon: Icon, hint } = meta[kind];

  return (
    <div className={cn("activity-intro", className)}>
      <div className="activity-intro__icon" aria-hidden>
        <Icon className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="label-mono">{hint}</p>
        <h2 className="activity-intro__title">{title}</h2>
        <p className="activity-intro__subtitle">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}

export function ActivityWorksheet({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("activity-worksheet p-4 sm:p-6", className)}>{children}</div>;
}

/** @deprecated use ActivityIntro */
export const ActivityHero = ActivityIntro;
