import { Link, usePathname, useRouter } from "@/components/router-link";
import {
  Activity,
  AudioLines,
  Bell,
  BookOpenText,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  LayoutDashboard,
  Library,
  MessagesSquare,
  PenLine,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { useAppThemeId } from "@/hooks/use-app-theme";
import { useSidebarBrandingExpanded } from "@/hooks/use-sidebar-branding";
import { LinguaFlowLogo } from "@/components/linguaflow-logo";
import { LearnerThemeSwitcher } from "@/components/learner-theme-switcher";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NavItem = { to: string; label: string; icon: LucideIcon };

/** LMS-style groups (always visible — no dropdown). */
const navSections: { label?: string; items: NavItem[] }[] = [
  {
    items: [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { to: "/analytics", label: "Your progress", icon: Activity },
    ],
  },
  {
    label: "Practice",
    items: [
      { to: "/tutor", label: "AI Tutor", icon: MessagesSquare },
      { to: "/speaking", label: "Speaking", icon: AudioLines },
      { to: "/quiz", label: "Quiz", icon: ClipboardList },
      { to: "/writing", label: "Writing", icon: PenLine },
      { to: "/flashcards", label: "Flashcards", icon: Sparkles },
    ],
  },
  {
    label: "Read & explore",
    items: [
      { to: "/reader", label: "Reader", icon: BookOpenText },
      { to: "/library", label: "Library", icon: Library },
      { to: "/vocabulary", label: "Vocabulary", icon: BookOpenText },
      { to: "/search", label: "Search", icon: Search },
    ],
  },
  {
    label: "Account",
    items: [{ to: "/settings", label: "Settings", icon: Settings }],
  },
];

const flatNav = navSections.flatMap((s) => s.items);

export function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const appTheme = useAppThemeId();
  const vitalityMode = appTheme === "classroom";
  const { expanded: brandingExpanded, toggle: toggleBranding } = useSidebarBrandingExpanded();
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const isActive = (to: string) => pathname === to || pathname.startsWith(`${to}/`);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <aside className="hidden h-full w-[260px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
        <div className="border-b border-sidebar-border px-5 py-5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <LinguaFlowLogo variant="sidebar" to="/dashboard" />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 rounded-lg text-muted-foreground"
              onClick={toggleBranding}
              aria-expanded={brandingExpanded}
              aria-label={brandingExpanded ? "Hide sidebar branding" : "Show sidebar branding"}
              title={brandingExpanded ? "Hide branding" : "Show branding"}
            >
              {brandingExpanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </Button>
          </div>
          {brandingExpanded ? (
            <div className="mt-3 space-y-1">
              {vitalityMode && (
                <p className="flex items-center gap-1.5 text-sm font-semibold text-primary">
                  <span aria-hidden>💚</span> Vitality
                </p>
              )}
              <p className="text-sm font-medium text-foreground">Learn any language</p>
              <p className="text-xs text-muted-foreground">AI tutor · library · speaking</p>
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">Language learning · A1–C1</p>
          )}
        </div>

        <nav className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 py-4">
          {navSections.map((section, i) => (
            <div key={section.label ?? `nav-${i}`}>
              {section.label ? (
                <p className="label-mono mb-1.5 px-3">{section.label}</p>
              ) : (
                <div className="mb-1 h-0" aria-hidden />
              )}
              <ul className="space-y-0.5">
                {section.items.map((item) => {
                  const active = isActive(item.to);
                  return (
                    <li key={item.to}>
                      <Link
                        to={item.to}
                        className={cn(
                          "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-[box-shadow,background-color] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          active
                            ? "neo-inset font-medium text-sidebar-accent-foreground"
                            : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                          vitalityMode && !active && "border border-transparent",
                        )}
                      >
                        <item.icon
                          className={cn("size-4 shrink-0", active ? "text-primary" : "")}
                          strokeWidth={1.75}
                        />
                        <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="mt-auto shrink-0">
          <LearnerThemeSwitcher />
          <div className="space-y-2 border-t border-sidebar-border p-4">
            <p className="truncate text-sm font-medium">{user?.display_name}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => {
                logout();
                router.push("/login");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header
          className={cn(
            "sticky top-0 z-20 px-5 py-4 backdrop-blur md:px-8",
            vitalityMode ? "vitality-shell-header" : "border-b border-border bg-background/90",
          )}
        >
          <div className="flex flex-wrap items-center gap-4">
            <div className="min-w-0 flex-1">
              <h1 className="truncate font-display text-xl font-semibold tracking-tight md:text-2xl">{title}</h1>
              <p className="truncate text-sm text-muted-foreground">{subtitle}</p>
            </div>
            {vitalityMode && (
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" className="rounded-xl" aria-label="Notifications">
                  <Bell className="size-5" strokeWidth={1.75} />
                </Button>
                <Button variant="ghost" size="icon" className="rounded-xl" asChild aria-label="Settings">
                  <Link to="/settings">
                    <Settings className="size-5" strokeWidth={1.75} />
                  </Link>
                </Button>
              </div>
            )}
            {actions}
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b border-border bg-muted/30 px-3 py-2 md:hidden">
          {flatNav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="whitespace-nowrap rounded-full px-3 py-1.5 text-xs text-muted-foreground data-[active=true]:bg-primary data-[active=true]:text-primary-foreground"
              data-active={isActive(item.to) || undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <main
          className={cn(
            "flex-1 px-5 py-6 md:px-8 md:py-8",
            vitalityMode ? "bg-background" : "bg-[color-mix(in_srgb,var(--background)_97%,var(--primary)_3%)]",
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
