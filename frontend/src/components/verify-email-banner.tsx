"use client";

/** One quiet line until the learner clicks the link in their inbox. */

import { useMutation } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

export function VerifyEmailBanner() {
  const user = useAuthStore((s) => s.user);

  const resend = useMutation({
    mutationFn: () =>
      apiFetch<{ sent: boolean }>("/auth/resend-verification", { method: "POST" }),
  });

  // Hidden for verified accounts AND for pre-feature accounts we can't judge
  // (email_verified undefined = older cached session; don't nag those).
  if (!user || user.email_verified !== false) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-primary/10 px-5 py-2 text-sm md:px-8">
      <MailCheck className="size-4 shrink-0 text-primary" aria-hidden />
      <span className="min-w-0">
        Please confirm your email — we sent a link to <span className="font-medium">{user.email}</span>.
      </span>
      <Button
        size="sm"
        variant="link"
        className="h-auto p-0 text-primary"
        disabled={resend.isPending || resend.isSuccess}
        onClick={() => resend.mutate()}
      >
        {resend.isSuccess ? "Sent — check your inbox" : resend.isPending ? "Sending…" : "Resend email"}
      </Button>
      {resend.isError && (
        <span className="text-xs text-destructive">
          {resend.error instanceof Error ? resend.error.message : "Couldn't resend just now."}
        </span>
      )}
    </div>
  );
}
