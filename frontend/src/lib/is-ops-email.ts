/** Ops accounts must use /admin/login — not the learner portal. */
export function isOpsEmail(email: string): boolean {
  const e = email.trim().toLowerCase();
  return e.includes("ops@") || e.includes("admin@");
}
