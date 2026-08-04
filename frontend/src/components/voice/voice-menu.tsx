"use client";

/** Topbar: pick the speaking partner's voice. Icon + short menu, no prose. */

import { useEffect, useState } from "react";
import { AudioLines, Check, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { knownVoices, playSpeakingAudio } from "@/lib/speaking-stream";
import { useVoiceStore } from "@/lib/voice-store";
import {
  availableGenders,
  personaById,
  VOICE_PERSONAS,
  type VoicePersonaId,
} from "@/lib/voice-persona";

const SAMPLE = "Hallo! Ich freue mich, mit dir Deutsch zu sprechen.";

export function VoiceMenu({ lang = "de-DE" }: { lang?: string }) {
  const personaId = useVoiceStore((s) => s.personaId);
  const setPersona = useVoiceStore((s) => s.setPersona);
  const [previewing, setPreviewing] = useState<VoicePersonaId | null>(null);
  const [genders, setGenders] = useState({ female: true, male: true });

  // The voice list loads asynchronously, so what this device can distinguish
  // isn't known on first paint.
  useEffect(() => {
    const read = () => setGenders(availableGenders(knownVoices(), lang));
    read();
    if (typeof speechSynthesis === "undefined") return;
    speechSynthesis.addEventListener("voiceschanged", read);
    return () => speechSynthesis.removeEventListener("voiceschanged", read);
  }, [lang]);

  async function preview(id: VoicePersonaId) {
    setPreviewing(id);
    await playSpeakingAudio(
      { use_browser_tts: true, text: SAMPLE, lang, data_uri: null },
      false,
      personaById(id),
    );
    setPreviewing(null);
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-muted-foreground hover:text-foreground"
          aria-label={`Speaking voice — ${personaById(personaId).label}`}
        >
          <AudioLines className="size-[18px]" strokeWidth={1.75} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-0">
        <p className="label-mono border-b border-border px-3 py-2.5">Voice</p>
        <ul className="p-1">
          {VOICE_PERSONAS.map((p) => {
            const active = p.id === personaId;
            return (
              <li key={p.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPersona(p.id)}
                  aria-pressed={active}
                  className={cn(
                    "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active && "font-medium",
                  )}
                >
                  <Check
                    className={cn("size-3.5 shrink-0", active ? "text-primary" : "opacity-0")}
                    aria-hidden
                  />
                  <span className="truncate">{p.label}</span>
                </button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-7 shrink-0"
                  disabled={previewing !== null}
                  onClick={() => void preview(p.id)}
                  aria-label={`Hear ${p.label.toLowerCase()}`}
                >
                  <Play
                    className={cn("size-3", previewing === p.id && "animate-pulse text-primary")}
                  />
                </Button>
              </li>
            );
          })}
        </ul>
        {/* Only shown when the device genuinely can't tell the options apart —
            otherwise the learner discovers it by ear and assumes it's broken. */}
        {!(genders.female && genders.male) && (
          <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
            One system voice installed — options sound alike.
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
