/**
 * Choosing who the speaking partner sounds like.
 *
 * The Web Speech API gives us a list of `SpeechSynthesisVoice` objects and
 * almost no metadata: a name, a language tag, and nothing else. There is no
 * gender field and no age field, so "a young woman's voice" cannot be
 * requested — it has to be approximated from the two things we can control:
 *
 *   1. WHICH voice — inferred from the voice's name, since installed voices are
 *      overwhelmingly named after a person ("Anna", "Markus"). Some platforms
 *      helpfully put "Female"/"Male" in the name, which is checked first.
 *   2. PITCH — a younger-sounding speaker is approximated by raising pitch
 *      slightly. This is a genuine approximation, not a real age control; it is
 *      convincing enough to be worth offering and honest to describe as
 *      "younger", which is what the UI calls it.
 *
 * Which voices exist is a property of the DEVICE, not the account — the German
 * voices on a Mac are not the ones on an Android phone. The learner's choice is
 * therefore stored locally rather than on their profile: syncing a preference
 * for a voice the next device doesn't have would be worse than not syncing.
 */

export type VoicePersonaId = "woman" | "man" | "young-woman" | "young-man";

export type VoicePersona = {
  id: VoicePersonaId;
  label: string;
  /** Which named voice to prefer. */
  gender: "female" | "male";
  /** 0–2 in the Web Speech API; 1 is the voice's natural pitch. */
  pitch: number;
  rate: number;
};

// Rates stay near 0.95: this is a language learner listening, and the platform
// default is brisk at A1/A2. The younger personas are a touch quicker because a
// higher pitch at a slow rate sounds sedated rather than young.
export const VOICE_PERSONAS: VoicePersona[] = [
  { id: "woman", label: "Woman", gender: "female", pitch: 1.0, rate: 0.95 },
  { id: "man", label: "Man", gender: "male", pitch: 1.0, rate: 0.95 },
  { id: "young-woman", label: "Younger woman", gender: "female", pitch: 1.35, rate: 1.0 },
  { id: "young-man", label: "Younger man", gender: "male", pitch: 1.25, rate: 1.0 },
];

export const DEFAULT_PERSONA: VoicePersonaId = "woman";

export function personaById(id: string | null | undefined): VoicePersona {
  return VOICE_PERSONAS.find((p) => p.id === id) ?? VOICE_PERSONAS[0];
}

/**
 * Given names found in platform voices, by language where it matters.
 *
 * Deliberately a list of names rather than a clever heuristic: the set of
 * installed voices is small and slow-moving, and a wrong guess here means a
 * learner who picked "Man" hears a woman — worse than falling back to the
 * default voice. Unknown names simply don't match either list.
 */
const FEMALE_NAMES = [
  // German
  "anna", "katja", "helena", "marlene", "vicki", "petra", "amala", "seraphina",
  // macOS's newer shared voice set, offered in every language it supports —
  // these are what an actual Mac reports for de-DE, so omitting them meant the
  // picker matched by luck (only "Anna" and "Reed" were recognised).
  "grandma", "shelley", "sandy", "flo", "bells", "bubbles", "superstar",
  // English
  "samantha", "victoria", "karen", "moira", "tessa", "fiona", "susan", "zira",
  "aria", "jenny", "michelle", "ava", "allison", "joanna", "kendra", "salli",
  // Other languages we ship
  "alice", "amelie", "amélie", "audrey", "monica", "mónica", "paulina", "luciana",
  "yelda", "milena", "zosia", "kyoko", "yuna", "sinji", "ting-ting", "meijia",
];

const MALE_NAMES = [
  // German
  "markus", "yannick", "conrad", "stefan", "hans", "reed", "viktor", "daniel",
  // macOS's newer shared voice set (see the note above).
  "grandpa", "eddy", "rocko", "junior", "ralph", "boing",
  // English
  "alex", "fred", "tom", "aaron", "arthur", "oliver", "rishi", "guy", "davis",
  "matthew", "brian", "eric", "joey", "russell",
  // Other languages we ship
  "thomas", "jorge", "diego", "luca", "felipe", "maged", "xander", "krzysztof",
  "otoya", "hattori", "yuri", "burcu", "liang",
];

function looksLike(name: string, gender: "female" | "male"): boolean {
  const lower = name.toLowerCase();
  // Some platforms label the voice outright; trust that over any name list.
  if (lower.includes("female")) return gender === "female";
  if (lower.includes("male")) return gender === "male"; // after "female", which contains "male"
  const list = gender === "female" ? FEMALE_NAMES : MALE_NAMES;
  return list.some((n) => lower.includes(n));
}

/**
 * The best available voice for `lang` matching the persona's gender.
 *
 * Falls back through: right language + right gender → right language → nothing
 * (which leaves the browser to pick). Language always outranks gender: a German
 * lesson read by an English voice is unintelligible, while the "wrong" gender
 * is merely not what was asked for.
 */
export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: string,
  persona: VoicePersona,
): SpeechSynthesisVoice | undefined {
  const prefix = lang.slice(0, 2).toLowerCase();
  const sameLanguage = voices.filter((v) => v.lang.toLowerCase().startsWith(prefix));
  return sameLanguage.find((v) => looksLike(v.name, persona.gender)) ?? sameLanguage[0];
}

/**
 * Which personas this device can actually distinguish.
 *
 * A device with only one German voice cannot honour "Man" vs "Woman" — the
 * picker would silently do nothing for two of its four options. The UI uses
 * this to say so rather than letting the learner discover it by ear.
 */
export function availableGenders(
  voices: SpeechSynthesisVoice[],
  lang: string,
): { female: boolean; male: boolean } {
  const prefix = lang.slice(0, 2).toLowerCase();
  const pool = voices.filter((v) => v.lang.toLowerCase().startsWith(prefix));
  return {
    female: pool.some((v) => looksLike(v.name, "female")),
    male: pool.some((v) => looksLike(v.name, "male")),
  };
}
