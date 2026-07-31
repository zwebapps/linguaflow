import { getAccessToken, getAuthPortal, useAuthStore } from "@/lib/auth-store";

/** Client-side checks for Next.js layouts; use `useRouter().replace` when false. */
export function isStudentAuthed(): boolean {
  if (typeof window === "undefined") return false;
  const token = getAccessToken();
  const portal = getAuthPortal();
  const user = useAuthStore.getState().user;
  return Boolean(token && portal === "student" && user?.role === "student");
}

export function isStudentOnboarded(): boolean {
  const user = useAuthStore.getState().user;
  return Boolean(user?.onboarded);
}

export function isAdminAuthed(): boolean {
  if (typeof window === "undefined") return false;
  const token = getAccessToken();
  const portal = getAuthPortal();
  const user = useAuthStore.getState().user;
  return Boolean(token && portal === "admin" && user?.role === "admin");
}

export function studentHomePath(): string {
  const user = useAuthStore.getState().user;
  return user?.onboarded ? "/dashboard" : "/onboarding";
}
