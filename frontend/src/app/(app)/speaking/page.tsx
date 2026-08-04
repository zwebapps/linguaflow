"use client";

import { Link } from "@/components/router-link";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { ChevronDown, Mic2 } from "lucide-react";
import { SpeakingSession } from "@/components/voice/speaking-session";
import { VoicePicker } from "@/components/voice/voice-picker";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import type { SpeakingScenario } from "@/lib/types";

export default function SpeakingPage() {
  const user = useAuthStore((s) => s.user);
  const level = user?.cefr_level ?? "B1";

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["speaking-scenarios"],
    queryFn: () => apiFetch<SpeakingScenario[]>("/speaking/scenarios"),
  });

  return (
    <AppShell
      title="Speaking practice"
      subtitle="Practice in your target language · live conversation · pronunciation guidance"
    >
      {isError && (
        <ErrorAlert
          message={error instanceof Error ? error.message : "Could not load scenarios"}
          onRetry={() => refetch()}
        />
      )}
      {isLoading && <Skeleton className="h-[520px] w-full rounded-2xl" />}
      {data && data.length > 0 && (
        <>
          <SpeakingSession scenarios={data} cefrLevel={level} />
          {/* Collapsed: changing voice is a once-in-a-while decision, and the
              session itself is what the page is for. */}
          <Collapsible className="panel group mt-4 rounded-lg">
            <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-4 py-3 text-left text-sm hover:bg-surface-raised/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Mic2 className="size-4 shrink-0 text-primary" />
              <span className="label-mono">Change the partner&apos;s voice</span>
              <ChevronDown
                className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
                aria-hidden
              />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="border-t border-border px-4 py-4">
                <VoicePicker />
              </div>
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No scenarios configured.{" "}
          <Link to="/tutor" className="text-primary underline">
            Use text chat
          </Link>{" "}
          instead.
        </p>
      )}
    </AppShell>
  );
}
