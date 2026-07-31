import { AdminGate } from "./admin-gate";

export default function AdminConsoleLayout({ children }: { children: React.ReactNode }) {
  return <AdminGate>{children}</AdminGate>;
}
