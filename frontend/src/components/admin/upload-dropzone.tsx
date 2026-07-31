import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiUpload } from "@/lib/api-upload";
import { validateIngestFile } from "@/lib/admin-ingest";
import type { AdminDocument, CefrLevel } from "@/lib/types";
import { cn } from "@/lib/utils";

export function UploadDropzone() {
  const queryClient = useQueryClient();
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [cefr, setCefr] = useState<CefrLevel | "">("");
  const [skill, setSkill] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pickFile = useCallback((f: File) => {
    const err = validateIngestFile(f);
    setError(err);
    if (err) {
      setFile(null);
      return;
    }
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }, [title]);

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a file first.");
      const err = validateIngestFile(file);
      if (err) throw new Error(err);
      const fd = new FormData();
      fd.append("file", file);
      if (title.trim()) fd.append("title", title.trim());
      if (cefr) fd.append("cefr_level", cefr);
      if (skill.trim()) fd.append("skill", skill.trim());
      setProgress(0);
      return apiUpload<AdminDocument>("/admin/documents", fd, setProgress);
    },
    onSuccess: () => {
      toast.success("Upload accepted — ingestion started");
      setFile(null);
      setProgress(null);
      setTitle("");
      void queryClient.invalidateQueries({ queryKey: ["admin-documents"] });
    },
    onError: (e) => {
      setProgress(null);
      toast.error(e instanceof Error ? e.message : "Upload failed");
    },
  });

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div>
        <h3 className="font-display text-sm font-semibold">Upload document</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          PDF, EPUB, DOCX, MD, HTML, or TXT · max 25 MB
        </p>
      </div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files[0];
          if (f) pickFile(f);
        }}
        className={cn(
          "flex flex-col items-center justify-center rounded-md border border-dashed px-4 py-8 text-center transition-colors",
          dragOver ? "border-data bg-data/10" : "border-data/30",
        )}
      >
        <Upload className="mb-2 size-8 text-data/80" strokeWidth={1.5} />
        <p className="text-sm text-muted-foreground">Drag and drop, or choose a file</p>
        <Input
          type="file"
          accept=".pdf,.epub,.docx,.md,.html,.htm,.txt"
          className="mt-3 max-w-xs"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) pickFile(f);
          }}
        />
        {file && (
          <p className="mt-2 font-mono text-xs text-foreground">
            {file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB
          </p>
        )}
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="upload-title">Title (optional)</Label>
          <Input id="upload-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label>CEFR (optional)</Label>
          <Select value={cefr || "none"} onValueChange={(v) => setCefr(v === "none" ? "" : (v as CefrLevel))}>
            <SelectTrigger>
              <SelectValue placeholder="—" />
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
          <Label htmlFor="upload-skill">Skill (optional)</Label>
          <Input
            id="upload-skill"
            placeholder="grammar, reading…"
            value={skill}
            onChange={(e) => setSkill(e.target.value)}
          />
        </div>
      </div>
      {progress !== null && (
        <div className="space-y-1">
          <p className="font-mono text-xs text-muted-foreground">Uploading… {progress}%</p>
          <Progress value={progress} className="h-2" />
        </div>
      )}
      <Button
        type="button"
        className="w-full bg-data text-data-foreground hover:bg-data/90"
        disabled={!file || !!error || upload.isPending}
        onClick={() => upload.mutate()}
      >
        {upload.isPending ? "Uploading…" : "Start ingestion"}
      </Button>
    </div>
  );
}
