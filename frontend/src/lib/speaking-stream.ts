import { API_BASE } from "./env";
import { getAccessToken } from "./auth-store";
import { ApiError } from "./api";
import type {
  ApiErrorBody,
  SpeakingStreamAudio,
  SpeakingStreamDone,
  SpeakingStreamError,
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

function germanVoice(): SpeechSynthesisVoice | undefined {
  const voices = speechSynthesis.getVoices();
  if (voices.length) cachedVoices = voices;
  const pool = voices.length ? voices : cachedVoices;
  return pool.find((v) => v.lang.toLowerCase().startsWith("de"));
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

export function playSpeakingAudio(payload: SpeakingStreamAudio, muted: boolean): void {
  if (muted) return;
  if (payload.use_browser_tts && payload.text) {
    const u = new SpeechSynthesisUtterance(payload.text);
    u.lang = payload.lang ?? "de-DE";
    const de = germanVoice();
    if (de) u.voice = de;
    // Slightly slower than default: this is a language learner listening, and the
    // platform default rate is brisk for someone at A1/A2.
    u.rate = 0.95;
    speechSynthesis.speak(u);
    return;
  }
  if (payload.data_uri) {
    const audio = new Audio(payload.data_uri);
    void audio.play();
  }
}
