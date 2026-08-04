import { create } from "zustand";
import { persist } from "zustand/middleware";
import { DEFAULT_PERSONA, type VoicePersonaId } from "@/lib/voice-persona";

/**
 * Which voice the speaking partner uses.
 *
 * Persisted locally, not on the profile: the installed voices differ per
 * device, so a choice that makes sense on a laptop may name a voice a phone
 * has never heard of. See `voice-persona.ts` for the full reasoning.
 */
type VoiceState = {
  personaId: VoicePersonaId;
  setPersona: (id: VoicePersonaId) => void;
};

export const useVoiceStore = create<VoiceState>()(
  persist(
    (set) => ({
      personaId: DEFAULT_PERSONA,
      setPersona: (personaId) => set({ personaId }),
    }),
    { name: "linguaflow.voice" },
  ),
);
