import { useEffect, useMemo, useState } from "react";
import { AudioLines, Mic, MicOff, PhoneOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/shared/spinner";
import { cn } from "@/lib/utils";

const BAR_COUNT = 40;

function VoiceWaveform({ active, level }: { active: boolean; level: number }) {
  const bars = useMemo(
    () =>
      Array.from({ length: BAR_COUNT }, (_, i) => {
        const center = BAR_COUNT / 2;
        const dist = Math.abs(i - center) / center;
        return 0.15 + (1 - dist) * 0.55;
      }),
    [],
  );

  return (
    <div className="flex h-16 w-full max-w-md items-center justify-center gap-[3px] px-4" aria-hidden>
      {bars.map((base, i) => {
        const h = active ? base * (0.35 + (level / 100) * 0.95) : base * 0.2;
        return (
          <span
            key={i}
            className="voice-canvas-bar w-[3px] rounded-full bg-[var(--voice-gold)]"
            style={{
              height: `${Math.round(h * 100)}%`,
              animationDelay: `${(i % 12) * 0.06}s`,
              animationPlayState: active ? "running" : "paused",
            }}
          />
        );
      })}
    </div>
  );
}

export function VoiceCanvas({
  cefrLevel,
  tutorName = "Anke",
  listening,
  level,
  muted,
  busy,
  statusLabel,
  onToggleMute,
  onRecordStart,
  onRecordStop,
}: {
  cefrLevel: string;
  tutorName?: string;
  listening: boolean;
  level: number;
  muted: boolean;
  busy?: boolean;
  statusLabel?: string | null;
  onToggleMute: () => void;
  onRecordStart: () => void;
  onRecordStop: () => void;
}) {
  const [holding, setHolding] = useState(false);

  useEffect(() => {
    if (!listening) setHolding(false);
  }, [listening]);

  const status = busy
    ? statusLabel ?? "Processing…"
    : listening
      ? `Recording · ${cefrLevel}`
      : `Hold to speak · ${cefrLevel} · ${tutorName}`;

  return (
    <div className="voice-canvas relative flex min-h-[min(480px,calc(100vh-14rem))] flex-col items-center justify-center overflow-hidden rounded-2xl border border-[var(--voice-ring)] px-6 py-10">
      <div className="pointer-events-none absolute inset-0 voice-canvas-bands" aria-hidden />

      <div className="relative z-10 flex flex-col items-center">
        <div className="relative mb-6 flex size-44 items-center justify-center">
          {[0, 1, 2, 3].map((ring) => (
            <span
              key={ring}
              className={cn(
                "voice-canvas-ring absolute rounded-full border border-[var(--voice-gold)]",
                !listening && !busy && "opacity-30",
              )}
              style={{
                inset: `${ring * 10}px`,
                animationDelay: `${ring * 0.35}s`,
                opacity: listening || busy ? undefined : 0.25,
              }}
            />
          ))}
          <div className="relative z-10 flex size-28 items-center justify-center rounded-full border border-[var(--voice-gold)]/40 bg-[var(--voice-orb)] shadow-[0_0_40px_-8px_var(--voice-glow)]">
            {busy ? (
              <Spinner label="" />
            ) : (
              <AudioLines className="size-12 text-[var(--voice-gold)]" strokeWidth={1.25} />
            )}
          </div>
        </div>

        <VoiceWaveform active={(listening && !muted) || !!busy} level={busy ? 40 : level} />

        <p className="label-mono mt-6 max-w-sm text-center text-[var(--voice-muted)]" aria-live="polite">
          {status}
        </p>

        <div className="mt-10 flex w-full max-w-sm gap-3">
          <Button
            type="button"
            variant="outline"
            className="flex-1 border-[var(--voice-muted)]/40 bg-transparent text-[var(--voice-fg)] hover:bg-white/5"
            disabled={busy}
            onClick={onToggleMute}
          >
            {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
            {muted ? "Unmute" : "Mute"}
          </Button>
          <Button
            type="button"
            className={cn(
              "flex-1 gap-2 text-white",
              listening ? "bg-[var(--voice-end)] hover:bg-[var(--voice-end)]/90" : "bg-[var(--voice-gold)] text-[var(--voice-bg)] hover:bg-[var(--voice-gold)]/90",
            )}
            disabled={busy}
            onPointerDown={(e) => {
              e.preventDefault();
              if (busy) return;
              setHolding(true);
              onRecordStart();
            }}
            onPointerUp={() => {
              if (holding || listening) onRecordStop();
              setHolding(false);
            }}
            onPointerLeave={() => {
              if (holding || listening) onRecordStop();
              setHolding(false);
            }}
          >
            {listening ? (
              <>
                <PhoneOff className="size-4" />
                Release to send
              </>
            ) : (
              <>Hold to talk</>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
