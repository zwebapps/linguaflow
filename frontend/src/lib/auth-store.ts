import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "./types";

const TOKEN_KEY = "df_access_token";
const PORTAL_KEY = "df_portal";

export type AuthPortal = "student" | "admin";

type AuthState = {
  token: string | null;
  user: User | null;
  portal: AuthPortal | null;
  setSession: (token: string, user: User, portal: AuthPortal) => void;
  setUser: (user: User) => void;
  logout: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      portal: null,
      setSession: (token, user, portal) => {
        if (typeof window !== "undefined") {
          localStorage.setItem(TOKEN_KEY, token);
          localStorage.setItem(PORTAL_KEY, portal);
        }
        set({ token, user, portal });
      },
      setUser: (user) => set({ user }),
      logout: () => {
        if (typeof window !== "undefined") {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(PORTAL_KEY);
        }
        set({ token: null, user: null, portal: null });
      },
    }),
    {
      name: "df-auth",
      partialize: (s) => ({ token: s.token, user: s.user, portal: s.portal }),
    },
  ),
);

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return useAuthStore.getState().token ?? localStorage.getItem(TOKEN_KEY);
}

export function getAuthPortal(): AuthPortal | null {
  if (typeof window === "undefined") return null;
  return useAuthStore.getState().portal ?? (localStorage.getItem(PORTAL_KEY) as AuthPortal | null);
}
