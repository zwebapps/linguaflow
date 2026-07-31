import { ArrowUp, Square } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { chatMessageSchema } from "@/lib/validation";

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  streaming,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  streaming?: boolean;
  disabled?: boolean;
}) {
  const len = value.length;
  const validation = chatMessageSchema.safeParse(value);
  const over = len > 4000;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (validation.success && !streaming) onSubmit();
      }}
      className="panel sticky bottom-4 rounded-lg p-3"
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (validation.success && !streaming) onSubmit();
          }
        }}
        rows={3}
        disabled={disabled || streaming}
        placeholder="Ask in your language or English — e.g. “Explain the dative case”…"
        className="w-full resize-none bg-transparent px-2 py-1 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
        aria-label="Message to tutor"
      />
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-2 pt-3">
        <Badge variant="secondary" className={`font-mono text-[10px] ${over ? "text-destructive" : ""}`}>
          {len}/4000
        </Badge>
        {!validation.success && value.length > 0 && (
          <span className="text-xs text-destructive">{validation.error.errors[0]?.message}</span>
        )}
        {streaming && onStop ? (
          <Button type="button" variant="secondary" size="sm" className="ml-auto gap-1.5" onClick={onStop}>
            <Square className="size-3.5" /> Stop
          </Button>
        ) : (
          <Button
            type="submit"
            size="sm"
            className="ml-auto gap-1.5"
            disabled={!validation.success || disabled}
          >
            Send <ArrowUp className="size-3.5" />
          </Button>
        )}
      </div>
    </form>
  );
}
