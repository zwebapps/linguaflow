import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { DocumentStatusBadge } from "@/components/admin/document-status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import type { AdminDocument } from "@/lib/types";

export function DocumentsTable({ items }: { items: AdminDocument[] }) {
  const queryClient = useQueryClient();

  const reingest = useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/admin/documents/${id}/reingest`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Re-ingestion started");
      void queryClient.invalidateQueries({ queryKey: ["admin-documents"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Reingest failed"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/admin/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Document removed");
      void queryClient.invalidateQueries({ queryKey: ["admin-documents"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No documents yet. Upload a file or add a link above.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Title</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>CEFR</TableHead>
          <TableHead>Chunks</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((d) => (
          <TableRow key={d.id}>
            <TableCell>
              <div className="min-w-0">
                {/* Link-created documents use the URL as their title, so this
                    is routinely a 1000px+ unbreakable string — the cell that
                    blew the whole table past the viewport. */}
                <p className="max-w-md truncate font-medium" title={d.title}>
                  {d.title}
                </p>
                {d.source_url && (
                  <p className="max-w-xs truncate font-mono text-[10px] text-muted-foreground">{d.source_url}</p>
                )}
                {d.status === "failed" && d.error && (
                  <p className="mt-1 text-xs text-destructive">{d.error}</p>
                )}
              </div>
            </TableCell>
            <TableCell className="font-mono text-xs">{d.source_type}</TableCell>
            <TableCell>{d.cefr_level ?? "—"}</TableCell>
            <TableCell>{d.chunk_count}</TableCell>
            <TableCell>
              <DocumentStatusBadge status={d.status} />
            </TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  title="Re-ingest"
                  disabled={reingest.isPending}
                  onClick={() => reingest.mutate(d.id)}
                >
                  <RefreshCw className="size-3.5" />
                </Button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button type="button" variant="ghost" size="icon" className="size-8 text-destructive">
                      <Trash2 className="size-3.5" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete document?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Removes &quot;{d.title}&quot; and purges its vectors from the index.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        onClick={() => remove.mutate(d.id)}
                      >
                        Delete
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
