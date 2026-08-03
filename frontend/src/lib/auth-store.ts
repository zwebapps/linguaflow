import { useEffect, useState } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "./types";

const TOKEN_KEY = "df_access_token";
const PORTAL_KEY = "df_portal";

export type AuthPortal = "student" | "admin";

type PortalSession = { token: string; user: User };

type AuthState = {
  token: string | null;
  user: User | null;
  portal: AuthPortal | null;
  /**
   * One saved session per portal. The learner app and the admin console used
   * to share the single token/portal slot, so signing into one silently
   * logged the other out — an admin who had also opened the learner app got
   * kicked to /admin/login on their next refresh. Each portal keeps its own
   * slot; the gates reactivate their portal's session instead of bouncing.
   */
  sessions: Partial<Record<AuthPortal, PortalSession>>;
  setSession: (token: string, user: User, portal: AuthPortal) => void;
  /** Make `portal`'s saved session the active one. False if none saved. */
  activatePortal: (portal: AuthPortal) => boolean;
  setUser: (user: User) => void;
  /** Sign out of one portal only (default: the active one). */
  logout: (portal?: AuthPortal) => void;
};

function mirrorActive(token: string | null, portal: AuthPortal | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  if (portal) localStorage.setItem(PORTAL_KEY, portal);
  else localStorage.removeItem(PORTAL_KEY);
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      portal: null,
      sessions: {},
      setSession: (token, user, portal) => {
        mirrorActive(token, portal);
        set((s) => ({
          token,
          user,
          portal,
          sessions: { ...s.sessions, [portal]: { token, user } },
        }));
      },
      activatePortal: (portal) => {
        const saved = get().sessions[portal];
        if (!saved) return false;
        mirrorActive(saved.token, portal);
        set({ token: saved.token, user: saved.user, portal });
        return true;
      },
      setUser: (user) =>
        set((s) => ({
          user,
          sessions:
            s.portal && s.sessions[s.portal]
              ? { ...s.sessions, [s.portal]: { ...s.sessions[s.portal]!, user } }
              : s.sessions,
        })),
      logout: (portal) => {
        const target = portal ?? get().portal;
        const sessions = { ...get().sessions };
        if (target) delete sessions[target];
        mirrorActive(null, null);
        set({ token: null, user: null, portal: null, sessions });
      },
    }),
    {
      name: "df-auth",
      partialize: (s) => ({
        token: s.token,
        user: s.user,
        portal: s.portal,
        sessions: s.sessions,
      }),
    },
  ),
);

/**
 * True once the persisted auth state has been rehydrated from localStorage.
 *
 * The login-blink bug: on a hard refresh the route gates ran their redirect
 * check while the store still held its initial null state — a logged-in user
 * bounced to /login for a frame and back. Gates must not decide anything
 * until this is true.
 */
export function useAuthHydrated(): boolean {
  // Always false on the server AND on the client's first render — gates that
  // branch on this therefore produce identical SSR and hydration output (no
  // hydration mismatch), and flip to the real UI one effect-tick later.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    if (useAuthStore.persist?.hasHydrated?.()) {
      setHydrated(true);
      return;
    }
    const unsub = useAuthStore.persist?.onFinishHydration?.(() => setHydrated(true));
    // No persist API at all would otherwise lock the gates shut forever.
    if (!unsub) setHydrated(true);
    return unsub;
  }, []);
  return hydrated;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return useAuthStore.getState().token ?? localStorage.getItem(TOKEN_KEY);
}

export function getAuthPortal(): AuthPortal | null {
  if (typeof window === "undefined") return null;
  return useAuthStore.getState().portal ?? (localStorage.getItem(PORTAL_KEY) as AuthPortal | null);
}
