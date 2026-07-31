import { Loader2 } from "lucide-react";

export function StatusIndicator({ label }: { label: string | null }) {
  if (!label) return null;
  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border bg-secondary/50 px-3 py-2 text-sm text-muted-foreground"
      aria-live="polite"
    >
      <Loader2 className="size-3.5 animate-spin text-signal" />
      <span>{label}</span>
    </div>
  );
}
