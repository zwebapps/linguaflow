import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/lib/types";

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <Badge
      variant="outline"
      className={
        status === "ready"
          ? "border-success/40 text-success"
          : status === "failed"
            ? "border-destructive/40 text-destructive"
            : "animate-pulse border-data/40 text-data"
      }
    >
      {status}
    </Badge>
  );
}
