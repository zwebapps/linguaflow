import { Link } from "@/components/router-link";
import { Download, MessageSquarePlus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { apiDownload, apiFetch } from "@/lib/api";
import type { ChatThreadSummary, Paginated } from "@/lib/types";

export function ThreadSidebar({
  activeId,
  onNew,
}: {
  activeId?: string | null;
  onNew: () => void;
}) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["chat-threads"],
    queryFn: () => apiFetch<Paginated<ChatThreadSummary>>("/chat/threads"),
  });

  const del = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/chat/threads/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-threads"] }),
  });

  async function exportThread(id: string, format: string) {
    const blob = await apiDownload(`/chat/threads/${id}/export?format=${format}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `thread-${id}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel flex h-full flex-col rounded-lg p-3">
      <Button variant="secondary" size="sm" className="mb-3 w-full gap-2" onClick={onNew}>
        <MessageSquarePlus className="size-3.5" /> New chat
      </Button>
      <p className="label-mono mb-2 px-1">Threads</p>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {isLoading &&
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        {data?.items.map((t) => (
          <div
            key={t.id}
            className={`group flex items-center gap-1 rounded-md pr-1 ${
              activeId === t.id ? "bg-secondary" : "hover:bg-secondary/50"
            }`}
          >
            <Link
              to="/tutor/$threadId"
              params={{ threadId: t.id }}
              className="min-w-0 flex-1 truncate px-3 py-2 text-sm"
            >
              {t.title}
            </Link>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="size-8 shrink-0 opacity-0 group-hover:opacity-100">
                  <Download className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {(["json", "csv", "md"] as const).map((f) => (
                  <DropdownMenuItem key={f} onClick={() => exportThread(t.id, f)}>
                    Export {f.toUpperCase()}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 opacity-0 group-hover:opacity-100"
              onClick={() => del.mutate(t.id)}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
