import { API_BASE } from "./env";
import {
  DEFAULT_PERSONA,
  personaById,
  pickVoice,
  type VoicePersona,
} from "./voice-persona";
import { getAccessToken } from "./auth-store";
import { ApiError } from "./api";
import type {
  ApiErrorBody,
  SpeakingStreamAudio,
  SpeakingStreamDone,
  SpeakingStreamError,
  SpeakingStreamFeedback,
  SpeakingStreamScores,
  SpeakingStreamStart,
  SpeakingStreamStatus,
  SpeakingStreamTranscript,
  SpeakingStreamUsage,
} from "./types";

export type SpeakingStreamHandlers = {
  onStart: (d: SpeakingStreamStart) => void;
  onStatus: (d: SpeakingStreamStatus) => void;
  onTranscript: (d: SpeakingStreamTranscript) => void;
  onToken: (d: { text: string }) => void;
  onScores: (d: SpeakingStreamScores) => void;
  onAudio: (d: SpeakingStreamAudio) => void;
  onUsage: (d: SpeakingStreamUsage) => void;
  onSessionFeedback?: (d: SpeakingStreamFeedback) => void;
  onDone: (d: SpeakingStreamDone) => void;
  onError: (d: SpeakingStreamError) => void;
};

async function toApiError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody = {
    error: { code: "internal_error", message: res.statusText || "Speaking turn failed" },
  };
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* empty */
  }
  return new ApiError(res.status, body);
}

function dispatchFrame(frame: string, handlers: SpeakingStreamHandlers) {
  const ev = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim();
  const raw = frame.match(/^data:\s*([\s\S]+)$/m)?.[1]?.trim();
  if (!ev || !raw) return;
  const d = JSON.parse(raw) as Record<string, unknown>;
  const map: Record<string, (payload: never) => void> = {
    start: handlers.onStart as (p: never) => void,
    status: handlers.onStatus as (p: never) => void,
    transcript: handlers.onTranscript as (p: never) => void,
    token: handlers.onToken as (p: never) => void,
    scores: handlers.onScores as (p: never) => void,
    audio: handlers.onAudio as (p: never) => void,
    usage: handlers.onUsage as (p: never) => void,
    session_feedback: (handlers.onSessionFeedback ?? (() => {})) as (p: never) => void,
    done: handlers.onDone as (p: never) => void,
    error: handlers.onError as (p: never) => void,
  };
  map[ev]?.(d as never);
}

export async function streamSpeakingTurn(
  form: FormData,
  handlers: SpeakingStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/speaking/turn`, {
    method: "POST",
    signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });

  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value.replace(/\r\n/g, "\n");
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const frame of frames) dispatchFrame(frame, handlers);
  }
}

/**
 * Pick a German voice, tolerating the async voice list.
 *
 * `getVoices()` returns [] until the engine has loaded its list, which on a cold
 * page is *after* the first turn finishes. Without this, turn one falls back to
 * whatever the platform default is — an English voice reading German aloud, which
 * teaches a learner the wrong pronunciation. So we prime the list once and prefer
 * a de-* voice when one exists.
 */
let cachedVoices: SpeechSynthesisVoice[] = [];

/** Every voice this device knows about, tolerating the async list. */
export function knownVoices(): SpeechSynthesisVoice[] {
  if (typeof speechSynthesis === "undefined") return cachedVoices;
  const voices = speechSynthesis.getVoices();
  if (voices.length) cachedVoices = voices;
  return voices.length ? voices : cachedVoices;
}

/** A voice for `lang` ("de-DE", "tr-TR", …) matching the learner's persona. */
function voiceFor(lang: string, persona: VoicePersona): SpeechSynthesisVoice | undefined {
  return pickVoice(knownVoices(), lang, persona);
}

export function primeSpeechVoices(): void {
  if (typeof speechSynthesis === "undefined") return;
  const load = () => {
    const v = speechSynthesis.getVoices();
    if (v.length) cachedVoices = v;
  };
  load();
  speechSynthesis.addEventListener("voiceschanged", load);
}

/**
 * Speak the tutor's reply. Resolves when playback actually ENDS — the
 * hands-free conversation loop must not reopen the mic while the tutor is
 * still talking, or the tutor transcribes itself.
 */
export function playSpeakingAudio(
  payload: SpeakingStreamAudio,
  muted: boolean,
  persona: VoicePersona = personaById(DEFAULT_PERSONA),
): Promise<void> {
  if (muted) return Promise.resolve();
  if (payload.use_browser_tts && payload.text) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(payload.text ?? "");
      // End-of-session feedback arrives with the LEARNER's language, not de-DE
      // — reading English coaching in a German voice is barely intelligible.
      u.lang = payload.lang ?? "de-DE";
      const voice = voiceFor(u.lang, persona);
      if (voice) u.voice = voice;
      // The persona carries its own rate: it is already slower than the
      // platform default, which is brisk for someone at A1/A2.
      u.rate = persona.rate;
      // Pitch is how a "younger" voice is approximated — no engine exposes age.
      u.pitch = persona.pitch;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      speechSynthesis.speak(u);
    });
  }
  if (payload.data_uri) {
    return new Promise((resolve) => {
      const audio = new Audio(payload.data_uri ?? undefined);
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      void audio.play().catch(() => resolve());
    });
  }
  return Promise.resolve();
}

/** Cut any in-flight tutor speech (used when the learner ends the session). */
export function cancelSpeakingAudio(): void {
  if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
}
