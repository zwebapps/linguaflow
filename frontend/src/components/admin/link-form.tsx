import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2 } from "lucide-react";
import { toast } from "sonner";
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
import { apiFetch } from "@/lib/api";
import type { AdminDocument, CefrLevel } from "@/lib/types";
import type { IngestLinkType } from "@/lib/admin-ingest";

export function LinkForm() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [sourceType, setSourceType] = useState<IngestLinkType>("web");
  const [title, setTitle] = useState("");
  const [cefr, setCefr] = useState<CefrLevel | "">("");
  const [skill, setSkill] = useState("");

  const submit = useMutation({
    mutationFn: () => {
      if (!url.trim()) throw new Error("URL is required.");
      try {
        new URL(url.trim());
      } catch {
        throw new Error("Enter a valid URL (include https://).");
      }
      return apiFetch<AdminDocument>("/admin/documents/link", {
        method: "POST",
        json: {
          url: url.trim(),
          source_type: sourceType,
          title: title.trim() || undefined,
          cefr_level: cefr || null,
          skill: skill.trim() || null,
        },
      });
    },
    onSuccess: () => {
      toast.success("Link queued for ingestion");
      setUrl("");
      setTitle("");
      void queryClient.invalidateQueries({ queryKey: ["admin-documents"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start gap-2">
        <Link2 className="mt-0.5 size-4 text-data" />
        <div>
          <h3 className="font-display text-sm font-semibold">Add link</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Web page, YouTube, or RSS URL</p>
        </div>
      </div>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="link-url">URL</Label>
          <Input
            id="link-url"
            type="url"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Type</Label>
          <Select value={sourceType} onValueChange={(v) => setSourceType(v as IngestLinkType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="web">Web</SelectItem>
              <SelectItem value="youtube">YouTube</SelectItem>
              <SelectItem value="rss">RSS</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="link-title">Title (optional)</Label>
          <Input id="link-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>CEFR (optional)</Label>
            <Select value={cefr || "none"} onValueChange={(v) => setCefr(v === "none" ? "" : (v as CefrLevel))}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">—</SelectItem>
                {(["A1", "A2", "B1", "B2", "C1"] as const).map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="link-skill">Skill (optional)</Label>
            <Input id="link-skill" value={skill} onChange={(e) => setSkill(e.target.value)} />
          </div>
        </div>
      </div>
      <Button
        type="button"
        variant="outline"
        className="w-full border-data/40"
        disabled={submit.isPending}
        onClick={() => submit.mutate()}
      >
        {submit.isPending ? "Adding…" : "Add to knowledge base"}
      </Button>
    </div>
  );
}
