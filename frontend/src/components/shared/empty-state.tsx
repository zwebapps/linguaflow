import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="panel flex flex-col items-center rounded-lg px-6 py-14 text-center">
      {icon && <div className="mb-4 text-muted-foreground">{icon}</div>}
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>
      {actionLabel && onAction && (
        <Button className="mt-6" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
