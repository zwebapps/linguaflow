import { Link, usePathname } from "@/components/router-link";
import { Activity, BookOpen, Brain, Database, FlaskConical, Rss } from "lucide-react";
import type { ReactNode } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { AdminRuntimeStatus } from "@/components/admin/admin-runtime-status";
import { Button } from "@/components/ui/button";

const adminNav = [
  { to: "/admin/knowledge-base", label: "Knowledge base", icon: Database },
  { to: "/admin/library", label: "Library", icon: BookOpen },
  { to: "/admin/models", label: "AI routes", icon: Brain },
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

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-card">
        <div className="border-b border-border px-4 py-5">
          <LinguaFlowLogo variant="sidebar" to="/admin/knowledge-base" />
          <p className="mt-2 font-mono text-[10px] text-muted-foreground">LinguaFlow · ops console</p>
        </div>
        <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
          {adminNav.map((item) => {
            const active = pathname.startsWith(item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-2 rounded-md px-3 py-2.5 text-sm ${
                  active ? "bg-data/15 text-data" : "text-muted-foreground hover:bg-data/10"
                }`}
              >
                <item.icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <AdminRuntimeStatus />
        <div className="mt-auto space-y-2 border-t border-border p-4 text-xs">
          <p className="text-sm font-medium">{user?.display_name}</p>
          <p className="text-muted-foreground">{user?.email}</p>
          <Button
            variant="outline"
            size="sm"
            className="w-full border-data/40"
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
        <header className="border-b border-border bg-background px-8 py-5">
          <h1 className="font-display text-xl font-semibold">{title}</h1>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </header>
        <main className="flex-1 bg-background p-8">{children}</main>
      </div>
    </div>
  );
}
