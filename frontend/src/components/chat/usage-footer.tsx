import type { ChatUsage } from "@/lib/types";

/** Learner view: response time only (no tokens, models, or cost). */
export function UsageFooter({
  usage,
}: {
  usage: ChatUsage & { latency_ms?: number; from_cache?: boolean };
  model?: string;
}) {
  const latency =
    usage.latency_ms != null ? `${(usage.latency_ms / 1000).toFixed(1)} s` : undefined;
  if (!latency) return null;
  return (
    <p className="text-xs text-muted-foreground">
      Response time · {latency}
      {usage.from_cache ? " · reused a recent answer" : ""}
    </p>
  );
}
