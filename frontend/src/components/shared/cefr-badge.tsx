import { Badge } from "@/components/ui/badge";
import type { CefrLevel } from "@/lib/types";

export function CefrBadge({ level }: { level: CefrLevel | string }) {
  return (
    <Badge variant="outline" className="border-data/40 font-mono text-[10px] text-data">
      {level}
    </Badge>
  );
}
