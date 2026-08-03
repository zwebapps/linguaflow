import { Link, usePathname } from "@/components/router-link";
import {
  Activity,
  BookOpen,
  Brain,
  Database,
  FlaskConical,
  Menu,
  Rss,
  ScrollText,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { AdminRuntimeStatus } from "@/components/admin/admin-runtime-status";
import { LearnerThemeSwitcher } from "@/components/learner-theme-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const adminNav = [
  { to: "/admin/knowledge-base", label: "Knowledge base", icon: Database },
  { to: "/admin/library", label: "Library", icon: BookOpen },
  { to: "/admin/models", label: "AI routes", icon: Brain },
  { to: "/admin/prompts", label: "Prompts", icon: ScrollText },
  { to: "/admin/feeds", label: "RSS feeds", icon: Rss },
  { to: "/admin/experiments", label: "A/B experiments", icon: FlaskConical },
  { to: "/admin/usage", label: "Usage & cost", icon: Activity },
] as const;

/** Ops portal — separate from learner UI */
export function AdminShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  // Mobile: same off-canvas drawer as the learner shell — the horizontal pill
  // strip it replaces hid most destinations off-screen. Navigation, the X,
  // the backdrop, and Escape all close it.
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [pathname]);
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      {navOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px] md:hidden"
          onClick={() => setNavOpen(false)}
          aria-hidden
        />
      )}
      <aside
        id="admin-sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex h-full w-64 shrink-0 flex-col border-r border-border bg-card transition-transform duration-200 md:static md:z-auto md:w-56 md:translate-x-0 md:transition-none",
          navOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="border-b border-border px-4 py-5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <LinguaFlowLogo variant="sidebar" to="/admin/knowledge-base" />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 rounded-lg text-muted-foreground md:hidden"
              onClick={() => setNavOpen(false)}
              aria-label="Close navigation"
            >
              <X className="size-4" />
            </Button>
          </div>
          <p className="mt-2 font-mono text-[10px] text-muted-foreground">LinguaFlow · ops console</p>
        </div>
        <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
          {adminNav.map((item) => {
            const active = pathname.startsWith(item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                  active
                    ? "neo-inset font-medium text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                }`}
              >
                <item.icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <AdminRuntimeStatus />
        <div className="mt-auto shrink-0">
          <LearnerThemeSwitcher />
        </div>
        <div className="space-y-2 border-t border-border p-4 text-xs">
          <p className="text-sm font-medium" suppressHydrationWarning>{user?.display_name}</p>
          <p className="text-muted-foreground" suppressHydrationWarning>{user?.email}</p>
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => {
              logout();
              window.location.href = "/admin/login";
            }}
          >
            Sign out
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="border-b border-border bg-background px-4 py-5 md:px-8">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0 rounded-xl md:hidden"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              aria-expanded={navOpen}
              aria-controls="admin-sidebar"
            >
              <Menu className="size-5" />
            </Button>
            <div className="min-w-0 flex-1">
              <h1 className="truncate font-display text-xl font-semibold">{title}</h1>
              <p className="truncate text-sm text-muted-foreground">{subtitle}</p>
            </div>
          </div>
        </header>
        <main className="flex-1 bg-background px-4 py-6 md:p-8">{children}</main>
      </div>
    </div>
  );
}
