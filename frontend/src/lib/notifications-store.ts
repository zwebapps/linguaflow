import { create } from "zustand";

/**
 * In-app notifications, session-scoped (in-memory on purpose — these are
 * "while you were here" nudges like a finished speaking session, not an inbox).
 */
export type AppNotification = {
  id: number;
  title: string;
  body?: string;
  at: number;
  read: boolean;
};

type NotificationsState = {
  items: AppNotification[];
  notify: (title: string, body?: string) => void;
  markAllRead: () => void;
};

let nextId = 1;

export const useNotificationsStore = create<NotificationsState>()((set) => ({
  items: [],
  notify: (title, body) =>
    set((s) => ({
      items: [{ id: nextId++, title, body, at: Date.now(), read: false }, ...s.items].slice(0, 20),
    })),
  markAllRead: () =>
    set((s) => ({ items: s.items.map((n) => ({ ...n, read: true })) })),
}));
