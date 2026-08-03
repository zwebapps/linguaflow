"use client";

/** Topbar bell: unread dot + a small popover of session-scoped notifications. */

import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useNotificationsStore } from "@/lib/notifications-store";

export function NotificationsBell() {
  const items = useNotificationsStore((s) => s.items);
  const markAllRead = useNotificationsStore((s) => s.markAllRead);
  const unread = items.filter((n) => !n.read).length;

  return (
    <Popover onOpenChange={(open) => open && markAllRead()}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative rounded-xl text-muted-foreground hover:text-foreground"
          aria-label={unread ? `Notifications — ${unread} unread` : "Notifications"}
        >
          <Bell className="size-[18px]" strokeWidth={1.75} />
          {unread > 0 && (
            <span
              aria-hidden
              className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary ring-2 ring-background"
            />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <p className="label-mono border-b border-border px-4 py-2.5">Notifications</p>
        {items.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            Nothing yet — finish a speaking session and it shows up here.
          </p>
        ) : (
          <ul className="max-h-80 overflow-y-auto">
            {items.map((n) => (
              <li key={n.id} className="border-b border-border/60 px-4 py-3 text-sm last:border-b-0">
                <p className="font-medium">{n.title}</p>
                {n.body && <p className="text-xs text-muted-foreground">{n.body}</p>}
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  {new Date(n.at).toLocaleTimeString()}
                </p>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
