import { AlertCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ErrorAlert({
  message,
  onRetry,
  retryLabel = "Retry",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
      <p className="min-w-0 flex-1 text-foreground">{message}</p>
      {onRetry && (
        <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onRetry}>
          <RotateCcw className="size-3.5" /> {retryLabel}
        </Button>
      )}
    </div>
  );
}
