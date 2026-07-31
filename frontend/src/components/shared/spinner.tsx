import { Loader2 } from "lucide-react";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin text-signal" aria-hidden />
      {label && <span>{label}</span>}
    </span>
  );
}
