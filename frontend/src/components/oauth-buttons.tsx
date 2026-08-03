"use client";

/**
 * "Continue with Google / Microsoft" buttons.
 *
 * The list comes from GET /auth/oauth/providers, which returns only the
 * providers whose credentials are configured server-side — an unconfigured
 * provider renders NO button (a button that 503s is worse than none).
 * Clicking hands the whole browser to the backend's /start endpoint; the
 * backend drives the provider round-trip and lands on /oauth/complete.
 */

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { API_BASE } from "@/lib/env";
import { Button } from "@/components/ui/button";

type ProviderInfo = { id: string; label: string };

function ProviderMark({ id }: { id: string }) {
  if (id === "google") {
    return (
      <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
        <path fill="#4285F4" d="M23.5 12.3c0-.9-.1-1.5-.3-2.2H12v4.1h6.5c-.1 1.1-.8 2.7-2.4 3.8l3.7 2.9c2.2-2 3.7-5 3.7-8.6z" />
        <path fill="#34A853" d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.7-2.9c-1 .7-2.4 1.2-4.2 1.2-3.2 0-5.9-2.1-6.8-5.1L1.3 17.2C3.3 21.2 7.3 24 12 24z" />
        <path fill="#FBBC05" d="M5.2 14.3c-.2-.7-.4-1.5-.4-2.3s.1-1.6.4-2.3L1.3 6.8C.5 8.4 0 10.1 0 12s.5 3.6 1.3 5.2l3.9-2.9z" />
        <path fill="#EA4335" d="M12 4.7c1.8 0 3 .8 3.7 1.4l2.7-2.6C16.9 1.3 14.2 0 12 0 7.3 0 3.3 2.8 1.3 6.8l3.9 2.9c.9-3 3.6-5 6.8-5z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
      <path fill="#F25022" d="M1 1h10v10H1z" />
      <path fill="#7FBA00" d="M13 1h10v10H13z" />
      <path fill="#00A4EF" d="M1 13h10v10H1z" />
      <path fill="#FFB900" d="M13 13h10v10H13z" />
    </svg>
  );
}

export function OAuthButtons({ intent }: { intent: "sign in" | "sign up" }) {
  const { data } = useQuery({
    queryKey: ["oauth-providers"],
    queryFn: () => apiFetch<ProviderInfo[]>("/auth/oauth/providers", { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  });

  if (!data?.length) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-xs text-muted-foreground">or</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      {data.map((p) => (
        <Button
          key={p.id}
          type="button"
          variant="outline"
          className="w-full gap-2"
          onClick={() => {
            window.location.href = `${API_BASE}/auth/oauth/${p.id}/start`;
          }}
        >
          <ProviderMark id={p.id} />
          Continue with {p.label}
          <span className="sr-only"> to {intent}</span>
        </Button>
      ))}
      {data.some((p) => p.id === "microsoft") && (
        <p className="text-center text-[11px] text-muted-foreground">
          Microsoft covers Hotmail, Outlook and Live accounts.
        </p>
      )}
    </div>
  );
}
