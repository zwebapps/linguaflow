import { useQuery } from "@tanstack/react-query";
import { CircleDot } from "lucide-react";
import { API_BASE, USE_MOCKS } from "@/lib/env";

type ReadyResponse = {
  status?: string;
  db?: boolean;
  vector_store?: boolean;
  redis?: boolean;
  llm?: boolean;
};

function apiOrigin(): string {
  return API_BASE.replace(/\/api\/v1\/?$/, "");
}

async function fetchReadyz(): Promise<ReadyResponse> {
  const res = await fetch(`${apiOrigin()}/readyz`);
  if (!res.ok) throw new Error("readyz failed");
  return res.json() as Promise<ReadyResponse>;
}

function StatusRow({ label, ok }: { label: string; ok: boolean | "warn" }) {
  const tone =
    ok === "warn" ? "text-warning" : ok ? "text-success" : "text-destructive";
  return (
    <li className="flex items-center gap-2">
      <CircleDot className={`size-3 shrink-0 ${tone}`} />
      <span className="leading-tight">{label}</span>
    </li>
  );
}

/** Ops sidebar — infrastructure / API readiness (not shown to learners). */
export function AdminRuntimeStatus() {
  const { data, isError } = useQuery({
    queryKey: ["admin-readyz"],
    queryFn: fetchReadyz,
    enabled: !USE_MOCKS,
    refetchInterval: 30_000,
    retry: 1,
  });

  if (USE_MOCKS) {
    return (
      <div className="space-y-2 border-t border-border p-4">
        <p className="label-mono text-[10px] text-muted-foreground">Runtime status</p>
        <ul className="space-y-2 text-xs text-muted-foreground">
          <StatusRow label="Qdrant vector store" ok={true} />
          <StatusRow label="Contract API (MSW)" ok={true} />
          <StatusRow label="Voice pipeline" ok="warn" />
        </ul>
      </div>
    );
  }

  const vectorOk = data?.vector_store === true;
  const apiOk = !isError && data?.db === true;
  const voiceOk = data?.llm === true ? true : data?.llm === false ? "warn" : false;

  return (
    <div className="space-y-2 border-t border-border p-4">
      <p className="label-mono text-[10px] text-muted-foreground">Runtime status</p>
      <ul className="space-y-2 text-xs text-muted-foreground">
        <StatusRow label="Qdrant vector store" ok={vectorOk} />
        <StatusRow label="API + database" ok={apiOk} />
        <StatusRow label="Voice pipeline (LLM key)" ok={voiceOk} />
      </ul>
    </div>
  );
}
