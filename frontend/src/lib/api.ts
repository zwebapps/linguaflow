import { API_BASE } from "./env";
import { getAccessToken } from "./auth-store";
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: ApiErrorBody["error"]["details"];
  retryAfter?: number;

  constructor(
    status: number,
    body: ApiErrorBody,
    retryAfter?: number,
  ) {
    super(body.error.message);
    this.name = "ApiError";
    this.code = body.error.code;
    this.status = status;
    this.details = body.error.details;
    this.retryAfter = retryAfter;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  const retryAfter = res.headers.get("Retry-After");
  let body: ApiErrorBody = {
    error: { code: "internal_error", message: res.statusText || "Request failed" },
  };
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* empty */
  }
  return new ApiError(
    res.status,
    body,
    retryAfter ? Number.parseInt(retryAfter, 10) : undefined,
  );
}

export type ApiFetchOptions = RequestInit & {
  auth?: boolean;
  json?: unknown;
};

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { auth = true, json, headers, ...rest } = options;
  const url = path.startsWith("http") ? path : `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;

  const method = (rest.method ?? (json !== undefined ? "POST" : "GET")).toUpperCase();
  const h = new Headers(headers);
  if (json !== undefined) h.set("Content-Type", "application/json");
  if (auth) {
    const token = getAccessToken();
    if (token) h.set("Authorization", `Bearer ${token}`);
  }

  const canHaveBody = method !== "GET" && method !== "HEAD";
  const body =
    json !== undefined && canHaveBody
      ? JSON.stringify(json)
      : canHaveBody
        ? rest.body
        : undefined;

  let res: Response;
  try {
    res = await fetch(url, {
      ...rest,
      method,
      headers: h,
      body,
    });
  } catch {
    throw new ApiError(0, {
      error: {
        code: "network_error",
        message: `Cannot reach the API at ${API_BASE}. Start the backend (port 8000) and check NEXT_PUBLIC_API_URL.`,
      },
    });
  }

  const isAuthAttempt =
    !auth ||
    path.includes("/auth/login") ||
    path.includes("/auth/register");

  if (res.status === 401 && typeof window !== "undefined" && !isAuthAttempt) {
    const { useAuthStore } = await import("./auth-store");
    useAuthStore.getState().logout();
    // Send each portal to ITS OWN sign-in page — an admin bounced to the
    // learner login reads as "the app logged me out and forgot who I am".
    const login = window.location.pathname.startsWith("/admin") ? "/admin/login" : "/login";
    window.location.href = `${login}?redirect=${encodeURIComponent(window.location.pathname)}`;
    throw await parseError(res);
  }

  if (!res.ok) throw await parseError(res);

  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return res as unknown as T;
}

export async function apiDownload(path: string): Promise<Blob> {
  const token = getAccessToken();
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw await parseError(res);
  return res.blob();
}
