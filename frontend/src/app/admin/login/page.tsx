import { Suspense } from "react";
import { AdminLoginForm } from "./admin-login-form";
import { Spinner } from "@/components/shared/spinner";

export default function AdminLoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <Spinner label="Loading…" />
        </div>
      }
    >
      <AdminLoginForm />
    </Suspense>
  );
}
