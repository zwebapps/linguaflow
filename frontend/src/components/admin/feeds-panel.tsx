import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import type { AdminFeed, CefrLevel } from "@/lib/types";

export function FeedsPanel({ items }: { items: AdminFeed[] }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [cefr, setCefr] = useState<CefrLevel>("B1");
  const [pollMinutes, setPollMinutes] = useState("1440");

  const add = useMutation({
    mutationFn: () => {
      if (!url.trim()) throw new Error("RSS URL is required.");
      return apiFetch<AdminFeed>("/admin/feeds", {
        method: "POST",
        json: {
          url: url.trim(),
          cefr_level: cefr,
          poll_interval_minutes: Number.parseInt(pollMinutes, 10) || 1440,
        },
      });
    },
    onSuccess: () => {
      toast.success("Feed added");
      setUrl("");
      void queryClient.invalidateQueries({ queryKey: ["admin-feeds"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/admin/feeds/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Feed removed");
      void queryClient.invalidateQueries({ queryKey: ["admin-feeds"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="font-display text-sm font-semibold">Add RSS feed</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Scheduled polling — separate from one-off RSS links on the knowledge base.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="feed-url">Feed URL</Label>
            <Input id="feed-url" placeholder="https://…/rss" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>CEFR</Label>
            <Select value={cefr} onValueChange={(v) => setCefr(v as CefrLevel)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["A1", "A2", "B1", "B2", "C1"] as const).map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="feed-poll">Poll interval (minutes)</Label>
            <Input id="feed-poll" type="number" value={pollMinutes} onChange={(e) => setPollMinutes(e.target.value)} />
          </div>
        </div>
        <Button
          type="button"
          className="mt-4 bg-data text-data-foreground hover:bg-data/90"
          disabled={add.isPending}
          onClick={() => add.mutate()}
        >
          <Plus className="size-4" />
          Add feed
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>URL</TableHead>
              <TableHead>CEFR</TableHead>
              <TableHead>Last polled</TableHead>
              <TableHead>Items</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((f) => (
              <TableRow key={f.id}>
                <TableCell className="max-w-md truncate font-mono text-xs">{f.url}</TableCell>
                <TableCell>{f.cefr_level}</TableCell>
                <TableCell className="text-xs">{f.last_polled_at ?? "—"}</TableCell>
                <TableCell>{f.items_ingested}</TableCell>
                <TableCell>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button type="button" variant="ghost" size="icon" className="size-8 text-destructive">
                        <Trash2 className="size-3.5" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Remove feed?</AlertDialogTitle>
                        <AlertDialogDescription>Stops polling {f.url}</AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => remove.mutate(f.id)}>Remove</AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
