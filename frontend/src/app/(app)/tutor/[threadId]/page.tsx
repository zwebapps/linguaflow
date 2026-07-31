"use client";

import { useParams } from "next/navigation";
import { TutorView } from "@/components/chat/tutor-view";

export default function TutorThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  return <TutorView threadId={threadId} />;
}
