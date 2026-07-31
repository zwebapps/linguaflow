import { StudentAppGate } from "./student-gate";

export default function LearnerAppLayout({ children }: { children: React.ReactNode }) {
  return <StudentAppGate>{children}</StudentAppGate>;
}
