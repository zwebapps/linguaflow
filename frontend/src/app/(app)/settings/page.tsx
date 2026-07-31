"use client";

import { Link } from "@/components/router-link";

import { useMutation } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import type { CefrLevel, User } from "@/lib/types";
import { toast } from "sonner";
import { ReaderThemePicker } from "@/components/reader/reader-theme-picker";
import { Slider } from "@/components/ui/slider";
import {
  getStoredReaderTheme,
  READER_FONT_SIZE_KEY,
  readerThemes,
  type ReaderThemeId,
} from "@/lib/reader-themes";
import { useState } from "react";
import { Switch } from "@/components/ui/switch";
import { useSidebarBrandingExpanded } from "@/hooks/use-sidebar-branding";

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [readerTheme, setReaderTheme] = useState<ReaderThemeId>(() => getStoredReaderTheme());
  const [readerSize, setReaderSize] = useState(() =>
    Number(typeof localStorage !== "undefined" ? localStorage.getItem(READER_FONT_SIZE_KEY) ?? "19" : "19"),
  );
  const { expanded: sidebarBranding, setExpanded: setSidebarBranding } = useSidebarBrandingExpanded();

  const save = useMutation({
    mutationFn: (patch: Partial<User>) => apiFetch<User>("/me", { method: "PATCH", json: patch }),
    onSuccess: (u) => {
      setUser(u);
      toast.success("Profile updated");
    },
  });

  if (!user) return null;

  return (
    <AppShell title="Settings" subtitle="Profile, appearance, and learning preferences">
      <div className="grid max-w-2xl gap-6">
        <div className="panel space-y-4 rounded-lg p-6">
          <h2 className="font-display text-lg font-semibold">Profile</h2>
        <div className="space-y-2">
          <Label>Display name</Label>
          <Input
            defaultValue={user.display_name ?? ""}
            onBlur={(e) => save.mutate({ display_name: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>CEFR level</Label>
          <Select
            defaultValue={user.cefr_level}
            onValueChange={(v) => save.mutate({ cefr_level: v as CefrLevel })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {["A1", "A2", "B1", "B2", "C1"].map((l) => (
                <SelectItem key={l} value={l}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Daily goal (minutes)</Label>
          <Input
            type="number"
            defaultValue={user.daily_goal_minutes ?? 20}
            onBlur={(e) => save.mutate({ daily_goal_minutes: Number(e.target.value) })}
          />
        </div>
        {save.isError && <ErrorAlert message={save.error.message} onRetry={() => save.mutate({})} />}
        </div>

        <div className="panel space-y-4 rounded-lg p-6">
          <h2 className="font-display text-lg font-semibold">Appearance</h2>
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label htmlFor="sidebar-branding">Sidebar branding</Label>
              <p className="text-sm text-muted-foreground">
                Show Vitality label and welcome text under the logo (or use the chevron next to the logo).
              </p>
            </div>
            <Switch
              id="sidebar-branding"
              checked={sidebarBranding}
              onCheckedChange={setSidebarBranding}
            />
          </div>
        </div>

        <div className="panel space-y-4 rounded-lg p-6">
          <h2 className="font-display text-lg font-semibold">Reader</h2>
          <p className="text-sm text-muted-foreground">
            Choose <strong>Vitality</strong>, <strong>Midnight</strong>, or <strong>Forest</strong> in the
            sidebar <strong>Theme</strong> control — the whole app and reading canvas stay in sync.
            Fine-tune font size and reading colors anytime via <strong>Reading display</strong> on{" "}
            <Link to="/reader" className="text-primary hover:underline">
              Reader
            </Link>{" "}
            or library texts (collapsible on desktop, bottom sheet on mobile).
          </p>
          <div className="space-y-2">
            <Label>Immersive Reader theme</Label>
            <ReaderThemePicker value={readerTheme} onChange={setReaderTheme} />
          </div>
          <div className="space-y-2">
            <Label>Reader font size · {readerSize}px</Label>
            <Slider
              value={[readerSize]}
              min={15}
              max={26}
              step={1}
              onValueChange={(v) => {
                setReaderSize(v[0]);
                localStorage.setItem(READER_FONT_SIZE_KEY, String(v[0]));
              }}
            />
          </div>
          <div
            className={`${readerTheme} rounded-lg border border-border p-4`}
            style={{ backgroundColor: "var(--reader-bg)", color: "var(--reader-fg)" }}
          >
            <p className="text-sm font-medium">{readerThemes.find((t) => t.id === readerTheme)?.label}</p>
            <p className="mt-1 text-xs" style={{ color: "var(--reader-accent)" }}>
              Preview — So beginnt eine Geschichte auf Deutsch.
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
