export const API_BASE =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

/** Mocks only when explicitly enabled (safe default for deploy). */
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
