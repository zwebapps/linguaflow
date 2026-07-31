import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
import type { AdminModel, AiRoute } from "@/lib/types";

function RouteEditorDialog({ route, models }: { route: AiRoute; models: AdminModel[] }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [primary, setPrimary] = useState(route.primary_model);
  const [fallbacks, setFallbacks] = useState(route.fallbacks.join(", "));
  const [temperature, setTemperature] = useState(String(route.params.temperature ?? 0.3));
  const [maxTokens, setMaxTokens] = useState(String(route.params.max_tokens ?? 1200));

  const save = useMutation({
    mutationFn: () =>
      apiFetch<AiRoute>(`/admin/ai-routes/${encodeURIComponent(route.task_type)}`, {
        method: "PUT",
        json: {
          primary_model: primary,
          fallbacks: fallbacks
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          params: {
            temperature: Number.parseFloat(temperature),
            max_tokens: Number.parseInt(maxTokens, 10),
          },
        },
      }),
    onSuccess: () => {
      toast.success("Route saved");
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["admin-routes"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="ghost" size="icon" className="size-8">
          <Pencil className="size-3.5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="border-border bg-card">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">{route.task_type}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Primary model</Label>
            <Select value={primary} onValueChange={setPrimary}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name} · ctx {Math.round(m.context_length / 1000)}k · $
                    {m.prompt_usd_per_1k}/1k in
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Fallbacks (comma-separated)</Label>
            <Input value={fallbacks} onChange={(e) => setFallbacks(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Temperature</Label>
              <Input value={temperature} onChange={(e) => setTemperature(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Max tokens</Label>
              <Input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            className="bg-data text-data-foreground hover:bg-data/90"
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save route"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ModelRouteEditor() {
  const routesQuery = useQuery({
    queryKey: ["admin-routes"],
    queryFn: () => apiFetch<{ routes: AiRoute[] }>("/admin/ai-routes"),
  });
  const modelsQuery = useQuery({
    queryKey: ["admin-models"],
    queryFn: () => apiFetch<{ models: AdminModel[] }>("/admin/models"),
  });

  const models = modelsQuery.data?.models ?? [];
  const routes = routesQuery.data?.routes ?? [];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Task</TableHead>
            <TableHead>Primary model</TableHead>
            <TableHead>Fallbacks</TableHead>
            <TableHead>Params</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {routes.map((r) => (
            <TableRow key={r.task_type}>
              <TableCell className="font-mono text-xs">{r.task_type}</TableCell>
              <TableCell className="font-mono text-xs">{r.primary_model}</TableCell>
              <TableCell className="font-mono text-xs">{r.fallbacks.join(", ") || "—"}</TableCell>
              <TableCell className="font-mono text-xs">
                T={r.params.temperature ?? "—"} · max {r.params.max_tokens ?? "—"}
              </TableCell>
              <TableCell>
                <RouteEditorDialog route={r} models={models.length ? models : [{ id: r.primary_model, name: r.primary_model, context_length: 128000, prompt_usd_per_1k: 0, completion_usd_per_1k: 0, supports_tools: true }]} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
