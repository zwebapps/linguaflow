"use client";

/** Choose who the speaking partner sounds like, and hear it before committing. */

import { useEffect, useState } from "react";
import { Check, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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

export function VoicePicker({ lang = "de-DE" }: { lang?: string }) {
  const personaId = useVoiceStore((s) => s.personaId);
  const setPersona = useVoiceStore((s) => s.setPersona);
  const [previewing, setPreviewing] = useState<VoicePersonaId | null>(null);
  // The voice list loads asynchronously, so what this device can distinguish
  // isn't known on first paint.
  const [genders, setGenders] = useState({ female: true, male: true });

  useEffect(() => {
    const read = () => setGenders(availableGenders(knownVoices(), lang));
    read();
    if (typeof speechSynthesis === "undefined") return;
    speechSynthesis.addEventListener("voiceschanged", read);
    return () => speechSynthesis.removeEventListener("voiceschanged", read);
  }, [lang]);

  // Only worth warning about when the device genuinely can't tell them apart.
  const oneVoiceOnly = !(genders.female && genders.male);

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
    <div className="space-y-3">
      <div>
        <p className="label-mono">Partner&apos;s voice</p>
        <p className="text-xs text-muted-foreground">
          Pick a voice, then press play to hear it.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {VOICE_PERSONAS.map((p) => {
          const active = p.id === personaId;
          return (
            <div
              key={p.id}
              className={cn(
                "flex items-center gap-2 rounded-lg border p-2 transition-colors",
                active ? "border-primary bg-primary/5" : "border-border",
              )}
            >
              <button
                type="button"
                onClick={() => setPersona(p.id)}
                aria-pressed={active}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Check
                  className={cn("size-4 shrink-0", active ? "text-primary" : "opacity-0")}
                  aria-hidden
                />
                <span className="truncate">{p.label}</span>
              </button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-8 shrink-0"
                disabled={previewing !== null}
                onClick={() => void preview(p.id)}
                aria-label={`Hear the ${p.label.toLowerCase()} voice`}
              >
                <Volume2
                  className={cn("size-4", previewing === p.id && "animate-pulse text-primary")}
                />
              </Button>
            </div>
          );
        })}
      </div>

      {oneVoiceOnly && (
        // Said plainly rather than letting the learner work it out by ear:
        // which voices exist is a property of the device, not of the app.
        <p className="text-xs text-muted-foreground">
          This device only has one voice installed for this language, so the
          options will sound similar. Adding more system voices gives you a
          wider choice.
        </p>
      )}
    </div>
  );
}
