import type { LucideIcon } from "lucide-react";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
}) {
  return (
    <div className="panel rounded-lg p-4">
      <div className="flex items-center justify-between">
        <p className="label-mono">{label}</p>
        <Icon className="size-4 text-signal" strokeWidth={1.75} />
      </div>
      <p className="mt-3 font-display text-3xl font-semibold">{value}</p>
      {hint && <p className="mt-1 font-mono text-xs text-data">{hint}</p>}
    </div>
  );
}
