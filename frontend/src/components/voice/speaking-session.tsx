import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceCanvas } from "@/components/voice/voice-canvas";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useNotificationsStore } from "@/lib/notifications-store";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { personaById } from "@/lib/voice-persona";
import { useVoiceStore } from "@/lib/voice-store";
import {
  cancelSpeakingAudio,
  playSpeakingAudio,
  primeSpeechVoices,
  streamSpeakingTurn,
} from "@/lib/speaking-stream";
import type {
  CefrLevel,
  SpeakingScenario,
  SpeakingStreamScores,
  SpeakingStreamUsage,
} from "@/lib/types";

export type SpeakingMode = "auto" | "hold";
export type SpeakingPhase = "idle" | "listening" | "sending" | "replying";

/**
 * One completed exchange, kept client-side so the learner can REPLAY their own
 * recording next to its corrections — hearing your own mistake is the feedback
 * that sticks. Audio lives in an object URL (never uploaded twice, revoked on
 * cleanup); nothing here goes to the server.
 */
type TurnRecord = {
  id: number;
  audioUrl: string;
  transcript: string | null;
  scores: SpeakingStreamScores | null;
};

/** End-of-session feedback, aggregated over every scored turn. */
type SessionSummary = {
  turns: number;
  overall: number;
  grammar: number;
  fluency: number;
  corrections: { original: string; suggestion: string; explanation: string }[];
};

function summarise(turnScores: SpeakingStreamScores[]): SessionSummary {
  const n = Math.max(1, turnScores.length);
  const avg = (pick: (s: SpeakingStreamScores) => number) =>
    turnScores.reduce((a, s) => a + pick(s), 0) / n;
  return {
    turns: turnScores.length,
    overall: avg((s) => s.overall),
    grammar: avg((s) => s.grammar),
    fluency: avg((s) => s.fluency),
    corrections: turnScores.flatMap((s) => s.corrections).slice(0, 12),
  };
}

/**
 * Voice-activity detection tuning.
 *
 * The old UI was push-to-hold: release too early and the last word was cut,
 * hold wrong and "No audio captured". The conversation loop instead keeps the
 * mic open and detects turns itself: the first ~600 ms of each listening
 * window calibrates the room's noise floor, speech starts when RMS clears the
 * floor for MIN_SPEECH_MS, and the turn auto-sends after END_SILENCE_MS of
 * quiet. Numbers are deliberately forgiving — a learner pausing to think
 * mid-sentence must NOT be cut off, so the end-of-turn silence is long.
 */
const CALIBRATE_MS = 600;
const MIN_SPEECH_MS = 300; // voiced this long → it's a real turn, not a cough
const END_SILENCE_MS = 1400; // pause this long after speaking → turn is over
const MAX_TURN_MS = 45_000; // hard stop so a stuck VAD can't record forever
const MIN_TURN_BYTES = 4096; // ignore blobs that can't contain speech

type VadState = {
  calibrating: boolean;
  calibrateStart: number;
  noiseSum: number;
  noiseSamples: number;
  noiseFloor: number;
  voiced: boolean;
  speechMs: number;
  silenceMs: number;
  turnStart: number;
  last: number;
};

function freshVad(now: number): VadState {
  return {
    calibrating: true,
    calibrateStart: now,
    noiseSum: 0,
    noiseSamples: 0,
    noiseFloor: 4,
    voiced: false,
    speechMs: 0,
    silenceMs: 0,
    turnStart: now,
    last: now,
  };
}

export function SpeakingSession({
  scenarios,
  cefrLevel,
  initialScenarioId,
}: {
  scenarios: SpeakingScenario[];
  cefrLevel: CefrLevel;
  initialScenarioId?: string;
}) {
  const [scenarioId, setScenarioId] = useState(
    // Default to a topic AT the learner's level, not merely the first entry.
    initialScenarioId ??
      scenarios.find((s) => s.cefr_level === cefrLevel)?.id ??
      scenarios[0]?.id ??
      "smalltalk",
  );
  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios[0];
  const levelsInOrder = (["A1", "A2", "B1", "B2", "C1"] as const).filter((lvl) =>
    scenarios.some((s) => s.cefr_level === lvl),
  );

  const [mode, setMode] = useState<SpeakingMode>("auto");
  const [phase, setPhase] = useState<SpeakingPhase>("idle");
  const [sessionActive, setSessionActive] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [muted, setMuted] = useState(false);
  // The learner's chosen voice. Read via a ref as well, because the streaming
  // callbacks below are created once and would otherwise capture the value it
  // had when the session started.
  const personaId = useVoiceStore((s) => s.personaId);
  const [level, setLevel] = useState(0);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState<string | null>(null);
  const [assistantReply, setAssistantReply] = useState("");
  const [scores, setScores] = useState<SpeakingStreamScores | null>(null);
  const [usage, setUsage] = useState<SpeakingStreamUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [micDenied, setMicDenied] = useState(false);
  const [turn, setTurn] = useState(1);
  const [totalTurns, setTotalTurns] = useState(10);
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  // The coach's end-of-session wrap-up (spoken + shown).
  const [coachFeedback, setCoachFeedback] = useState<string | null>(null);
  const [turns, setTurns] = useState<TurnRecord[]>([]);
  const turnScoresRef = useRef<SpeakingStreamScores[]>([]);
  const completeRef = useRef(false);
  const turnIdRef = useRef(0);

  // Object-URL bookkeeping lives in a ref too: state updaters don't run on an
  // unmounted component, and a leaked blob URL pins the whole recording.
  const turnUrlsRef = useRef<string[]>([]);

  const clearTurns = useCallback(() => {
    turnUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    turnUrlsRef.current = [];
    setTurns([]);
  }, []);

  useEffect(() => {
    const urls = turnUrlsRef.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const sessionRef = useRef(false);
  const modeRef = useRef<SpeakingMode>("auto");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number>(0);
  const vadRef = useRef<VadState>(freshVad(0));
  const discardRef = useRef(false);
  const mutedRef = useRef(false);
  const personaRef = useRef(personaById(personaId));
  const abortRef = useRef<AbortController | null>(null);
  // sendTurn (defined first) and beginListening (defined after) call each
  // other across turns; the ref breaks the circular capture without stale
  // closures.
  const beginListeningRef = useRef<() => void>(() => {});

  modeRef.current = mode;
  mutedRef.current = muted;
  personaRef.current = personaById(personaId);

  const stopMeter = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    setLevel(0);
    setUserSpeaking(false);
  }, []);

  const releaseStream = useCallback(() => {
    stopMeter();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close().catch(() => undefined);
    audioCtxRef.current = null;
    analyserRef.current = null;
  }, [stopMeter]);

  useEffect(
    () => () => {
      sessionRef.current = false;
      discardRef.current = true;
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      releaseStream();
      abortRef.current?.abort();
      cancelSpeakingAudio();
    },
    [releaseStream],
  );

  // Warm the voice list on mount: getVoices() is empty until the engine loads it,
  // so without this the first spoken reply can come out in an English voice.
  useEffect(() => {
    primeSpeechVoices();
  }, []);

  useEffect(() => {
    setAssistantReply("");
    setLastTranscript(null);
    setScores(null);
    setUsage(null);
    setError(null);
    // A different scenario is a different role-play: fresh thread, fresh count.
    setThreadId(null);
    setTurn(1);
    setSummary(null);
    setCoachFeedback(null);
    turnScoresRef.current = [];
    clearTurns();
  }, [scenarioId, clearTurns]);

  const speakOpening = useCallback(() => {
    if (!scenario?.opening || muted) return;
    void playSpeakingAudio(
      { use_browser_tts: true, text: scenario.opening, lang: "de-DE", data_uri: null },
      muted,
      personaById(personaId),
    );
  }, [scenario?.opening, muted, personaId]);

  /** RMS 0–100 from the time-domain signal — steadier than frequency averages. */
  const readRms = useCallback((): number => {
    const analyser = analyserRef.current;
    if (!analyser) return 0;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    return Math.min(100, Math.sqrt(sum / data.length) * 260);
  }, []);

  const endTurn = useCallback(() => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }, []);

  const vadTick = useCallback(() => {
    const rms = readRms();
    setLevel(rms);
    const now = performance.now();
    const vad = vadRef.current;
    const dt = Math.min(200, now - vad.last);
    vad.last = now;

    if (vad.calibrating) {
      vad.noiseSum += rms;
      vad.noiseSamples += 1;
      if (now - vad.calibrateStart >= CALIBRATE_MS) {
        vad.noiseFloor = vad.noiseSamples ? vad.noiseSum / vad.noiseSamples : 4;
        vad.calibrating = false;
      }
      rafRef.current = requestAnimationFrame(vadTick);
      return;
    }

    // Adaptive thresholds: clearly above the room, with hysteresis so a
    // trailing consonant doesn't flap the state machine.
    const startTh = Math.max(vad.noiseFloor * 2.2, 7);
    const endTh = Math.max(vad.noiseFloor * 1.5, 5);

    if (rms >= startTh) {
      vad.speechMs += dt;
      vad.silenceMs = 0;
      if (!vad.voiced && vad.speechMs >= MIN_SPEECH_MS) {
        vad.voiced = true;
        setUserSpeaking(true);
      }
    } else if (rms < endTh) {
      if (vad.voiced) vad.silenceMs += dt;
      else vad.speechMs = Math.max(0, vad.speechMs - dt);
    }

    if (modeRef.current === "auto" && vad.voiced) {
      if (vad.silenceMs >= END_SILENCE_MS || now - vad.turnStart >= MAX_TURN_MS) {
        setUserSpeaking(false);
        endTurn();
        return; // recorder.onstop drives what happens next
      }
    }

    rafRef.current = requestAnimationFrame(vadTick);
  }, [endTurn, readRms]);

  const sendTurn = useCallback(
    async (blob: Blob) => {
      setPhase("sending");
      setStatusLabel("Transcribing…");
      setAssistantReply("");
      setScores(null);
      setError(null);

      // Keep the recording so the learner can replay their own voice next to
      // the corrections. Filled in as the stream's frames arrive.
      const turnId = ++turnIdRef.current;
      const audioUrl = URL.createObjectURL(blob);
      turnUrlsRef.current.push(audioUrl);
      setTurns((prev) => [
        { id: turnId, audioUrl, transcript: null, scores: null },
        ...prev,
      ]);
      const patchTurn = (patch: Partial<TurnRecord>) =>
        setTurns((prev) => prev.map((t) => (t.id === turnId ? { ...t, ...patch } : t)));

      const form = new FormData();
      form.append("audio", blob, "turn.webm");
      form.append("scenario", scenarioId);
      form.append("cefr_level", cefrLevel);
      form.append("want_audio", "true");
      if (threadId) form.append("thread_id", threadId);

      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      let playback: Promise<void> = Promise.resolve();
      try {
        await streamSpeakingTurn(
          form,
          {
            onStart: (d) => {
              setThreadId(d.thread_id);
              if (d.turn) setTurn(d.turn);
              if (d.total_turns) setTotalTurns(d.total_turns);
            },
            onStatus: (d) => setStatusLabel(d.label),
            onTranscript: (d) => {
              setLastTranscript(d.text);
              patchTurn({ transcript: d.text });
            },
            onToken: (d) => setAssistantReply((prev) => prev + d.text),
            onScores: (d) => {
              setScores(d);
              turnScoresRef.current.push(d);
              patchTurn({ scores: d });
            },
            onAudio: (d) => {
              setPhase("replying");
              setStatusLabel(null);
              // The final turn emits TWO audio frames (in-character goodbye,
              // then the coach's feedback). Chain, don't replace, or the
              // second cuts the first off and the await returns early.
              const prev = playback;
              playback = prev.then(() =>
                playSpeakingAudio(d, mutedRef.current, personaRef.current),
              );
            },
            onSessionFeedback: (d) => setCoachFeedback(d.text),
            onUsage: (d) => setUsage(d),
            onDone: (d) => {
              setStatusLabel(null);
              completeRef.current = d.session_complete === true;
              // An unintelligible turn: the tutor asked them to repeat and no
              // question was consumed, so drop the dud from the turn list.
              if (d.retry) setTurns((prev) => prev.filter((t) => t.id !== turnId));
            },
            onError: (d) => {
              setError(d.message);
              setStatusLabel(null);
            },
          },
          ac.signal,
        );
      } catch (e) {
        if (!ac.signal.aborted) {
          setError(e instanceof Error ? e.message : "Speaking turn failed");
        }
      }

      // Wait for the tutor to FINISH talking before the mic reopens —
      // otherwise the next turn transcribes the tutor's own voice.
      await playback;

      if (completeRef.current) {
        // Ten questions asked and answered — the session is over. Close the
        // mic and hand over the aggregated feedback.
        completeRef.current = false;
        const s = summarise(turnScoresRef.current);
        setSummary(s);
        useNotificationsStore
          .getState()
          .notify(
            "Speaking session complete 🎉",
            `${s.turns} turns · overall ${Math.round(s.overall * 100)}% · ${s.corrections.length} correction${s.corrections.length === 1 ? "" : "s"} to review`,
          );
        sessionRef.current = false;
        setSessionActive(false);
        releaseStream();
        setPhase("idle");
        setStatusLabel(null);
      } else if (sessionRef.current && modeRef.current === "auto" && streamRef.current) {
        beginListeningRef.current();
      } else {
        setPhase("idle");
        setStatusLabel(null);
      }
    },
    [scenarioId, cefrLevel, threadId, releaseStream],
  );

  /** Open a fresh recorder on the live stream and start the VAD loop. */
  const beginListening = useCallback(() => {
    const stream = streamRef.current;
    if (!stream || !sessionRef.current) return;

    chunksRef.current = [];
    discardRef.current = false;
    vadRef.current = freshVad(performance.now());
    setUserSpeaking(false);

    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : undefined;
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorderRef.current = rec;
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      const voiced = vadRef.current.voiced;
      const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
      if (discardRef.current) return;
      if (voiced && blob.size >= MIN_TURN_BYTES) {
        void sendTurn(blob);
      } else if (sessionRef.current && modeRef.current === "auto") {
        // Nothing worth sending (noise blip) — quietly keep listening.
        beginListeningRef.current();
      } else {
        setPhase("idle");
        if (modeRef.current === "hold") setError("I couldn't hear you — try speaking a bit longer.");
      }
    };
    rec.start(250);
    setPhase("listening");
    rafRef.current = requestAnimationFrame(vadTick);
  }, [sendTurn, vadTick]);
  beginListeningRef.current = beginListening;

  const openMic = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) return true;
    setError(null);
    setMicDenied(false);
    try {
      // Echo cancellation + noise suppression are what make hands-free viable:
      // without them the tutor's own TTS and room noise leak into the turn.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      return true;
    } catch {
      setMicDenied(true);
      return false;
    }
  }, []);

  const startConversation = useCallback(async () => {
    if (!(await openMic())) return;
    // Every Start is a fresh 10-question session — a finished thread would
    // otherwise wrap up again on its very first turn.
    setThreadId(null);
    setTurn(1);
    setSummary(null);
    setCoachFeedback(null);
    turnScoresRef.current = [];
    clearTurns();
    completeRef.current = false;
    sessionRef.current = true;
    setSessionActive(true);
    // Natural opening: the tutor greets first, then the floor is yours.
    if (scenario?.opening && !mutedRef.current) {
      setPhase("replying");
      await playSpeakingAudio(
        { use_browser_tts: true, text: scenario.opening, lang: "de-DE", data_uri: null },
        mutedRef.current,
        personaRef.current,
      );
    }
    // Via the ref: the awaits above straddle renders, and a stale closure here
    // would carry the previous session's thread id into the first turn.
    if (sessionRef.current) beginListeningRef.current();
  }, [clearTurns, openMic, scenario?.opening]);

  const endConversation = useCallback(() => {
    sessionRef.current = false;
    setSessionActive(false);
    discardRef.current = true;
    abortRef.current?.abort();
    cancelSpeakingAudio();
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    releaseStream();
    setPhase("idle");
    setStatusLabel(null);
  }, [releaseStream]);

  // Hold-to-talk fallback (noisy rooms, no-headset laptops). No session state:
  // each press is one turn, and the scenario picker stays usable between turns.
  const holdStart = useCallback(async () => {
    if (!(await openMic())) return;
    sessionRef.current = true;
    beginListeningRef.current();
    // In hold mode the button is the VAD: mark the turn voiced immediately.
    vadRef.current.voiced = true;
    vadRef.current.calibrating = false;
    setUserSpeaking(true);
  }, [openMic]);

  const holdStop = useCallback(() => {
    setUserSpeaking(false);
    endTurn();
  }, [endTurn]);

  const busy = phase === "sending";

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={scenarioId}
            onValueChange={setScenarioId}
            disabled={sessionActive || busy}
          >
            <SelectTrigger className="w-full max-w-xs rounded-xl">
              <SelectValue placeholder="Scenario" />
            </SelectTrigger>
            <SelectContent>
              {levelsInOrder.map((lvl) => (
                <SelectGroup key={lvl}>
                  <SelectLabel>
                    {lvl}
                    {lvl === cefrLevel ? " · your level" : ""}
                  </SelectLabel>
                  {scenarios
                    .filter((s) => s.cefr_level === lvl)
                    .map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.title}
                      </SelectItem>
                    ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="rounded-xl"
            onClick={speakOpening}
            disabled={muted || sessionActive}
          >
            Hear opening
          </Button>
        </div>

        {scenario && (
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card/80 px-4 py-3">
            <p className="min-w-0 flex-1 truncate text-sm italic text-muted-foreground">
              „{scenario.opening}&ldquo;
            </p>
            {sessionActive && (
              <Badge variant="secondary" className="shrink-0">
                Question {turn} / {totalTurns}
              </Badge>
            )}
          </div>
        )}

        {micDenied && (
          <ErrorAlert
            message="Microphone access is blocked. Allow the mic in your browser settings and try again."
            onRetry={() => setMicDenied(false)}
          />
        )}
        {error && <ErrorAlert message={error} onRetry={() => setError(null)} />}

        <VoiceCanvas
          cefrLevel={cefrLevel}
          tutorName={scenario?.title ?? "Tutor"}
          mode={mode}
          sessionActive={sessionActive}
          phase={phase}
          userSpeaking={userSpeaking}
          level={level}
          muted={muted}
          statusLabel={statusLabel}
          onToggleMute={() => setMuted((m) => !m)}
          onToggleMode={() => {
            endConversation();
            setMode((m) => (m === "auto" ? "hold" : "auto"));
          }}
          onSessionStart={() => void startConversation()}
          onSessionEnd={endConversation}
          onHoldStart={() => void holdStart()}
          onHoldStop={holdStop}
        />

        <p className="text-center text-xs text-muted-foreground">
          {mode === "auto"
            ? "Start the conversation, then just talk — your turn sends itself when you pause."
            : "Push and hold to speak · release to send."}{" "}
          Transcribed and answered in your target language.
        </p>
      </div>

      <aside className="space-y-4">
        {summary && (
          <div className="neo-card panel space-y-3 rounded-xl border-2 border-primary/30 p-4">
            <div className="flex items-center gap-2">
              <p className="label-mono">Session complete 🎉</p>
              <Badge variant="secondary">{summary.turns} turns</Badge>
            </div>
            {coachFeedback && (
              // Spoken aloud in the learner's own language as it appears —
              // shown too, so it can be re-read after the audio has passed.
              <p className="rounded-lg bg-primary/10 p-3 text-sm leading-relaxed">
                🎧 {coachFeedback}
              </p>
            )}
            <ul className="space-y-1 text-sm">
              <li>Overall · {Math.round(summary.overall * 100)}%</li>
              <li>Grammar · {Math.round(summary.grammar * 100)}%</li>
              <li>Fluency · {Math.round(summary.fluency * 100)}%</li>
            </ul>
            {summary.corrections.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">
                  What to practise next — from this session:
                </p>
                {summary.corrections.map((c, i) => (
                  <div key={i} className="border-t border-border pt-2 text-xs">
                    <p>
                      <span className="line-through opacity-70">{c.original}</span> → {c.suggestion}
                    </p>
                    <p className="text-muted-foreground">{c.explanation}</p>
                  </div>
                ))}
              </div>
            )}
            <Button size="sm" variant="secondary" onClick={() => setSummary(null)}>
              Dismiss
            </Button>
          </div>
        )}
        <div className="neo-card panel rounded-xl p-4">
          <p className="label-mono mb-2">Your last turn</p>
          {busy && !lastTranscript && <Spinner label={statusLabel ?? "Processing…"} />}
          {lastTranscript ? (
            <p className="text-sm">{lastTranscript}</p>
          ) : (
            !busy && (
              <p className="text-sm text-muted-foreground">Say something to see your transcript.</p>
            )
          )}
        </div>

        <div className="neo-card panel rounded-xl p-4">
          <p className="label-mono mb-2">Tutor reply</p>
          {assistantReply ? (
            <p className="text-sm leading-relaxed">{assistantReply}</p>
          ) : (
            <p className="text-sm text-muted-foreground">Reply streams here after each turn.</p>
          )}
        </div>

        {turns.length > 0 && (
          <div className="neo-card panel space-y-3 rounded-xl p-4">
            <p className="label-mono">Your turns — listen back</p>
            <p className="text-xs text-muted-foreground">
              Replay your own voice next to the correction — that&apos;s where mistakes stick.
            </p>
            <ul className="space-y-3">
              {turns.map((t, idx) => (
                <li key={t.id} className="space-y-1.5 border-t border-border pt-2 first:border-t-0 first:pt-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="shrink-0 text-[10px]">
                      Turn {turns.length - idx}
                    </Badge>
                    {t.scores && (
                      <span className="text-xs text-muted-foreground">
                        {Math.round(t.scores.overall * 100)}% overall
                      </span>
                    )}
                  </div>
                  {/* Learner's own speech; the transcript below is the caption. */}
                  <audio controls preload="metadata" src={t.audioUrl} className="h-8 w-full" />
                  {t.transcript && <p className="text-xs italic">„{t.transcript}&ldquo;</p>}
                  {t.scores?.corrections.map((c, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <button
                        type="button"
                        className="mt-0.5 shrink-0 text-primary underline-offset-2 hover:underline"
                        aria-label="Hear the corrected sentence"
                        title="Hear it said correctly"
                        onClick={() =>
                          void playSpeakingAudio(
                            { use_browser_tts: true, text: c.suggestion, lang: "de-DE", data_uri: null },
                            false,
                            personaRef.current,
                          )
                        }
                      >
                        🔊
                      </button>
                      <p>
                        <span className="line-through opacity-70">{c.original}</span> →{" "}
                        <span className="font-medium">{c.suggestion}</span>
                        <span className="block text-muted-foreground">{c.explanation}</span>
                      </p>
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        )}

        {scores && (
          <div className="neo-card panel space-y-3 rounded-xl p-4">
            <div className="flex flex-wrap items-center gap-2">
              <p className="label-mono">Feedback</p>
              <Badge variant="secondary">{scores.cefr_level}</Badge>
            </div>
            {scores.pronunciation_is_approximate && (
              <p className="text-xs text-muted-foreground">
                Pronunciation score is approximate guidance (V1), not a graded test.
              </p>
            )}
            <ul className="space-y-1 text-sm">
              <li>Overall · {Math.round(scores.overall * 100)}%</li>
              <li>Grammar · {Math.round(scores.grammar * 100)}%</li>
              <li>Fluency · {Math.round(scores.fluency * 100)}%</li>
            </ul>
            {scores.corrections.map((c, i) => (
              <div key={i} className="border-t border-border pt-2 text-xs">
                <p>
                  <span className="line-through opacity-70">{c.original}</span> → {c.suggestion}
                </p>
                <p className="text-muted-foreground">{c.explanation}</p>
              </div>
            ))}
          </div>
        )}

        {usage && (
          <p className="font-mono text-[10px] text-muted-foreground">
            {usage.model} · {usage.tokens_in}/{usage.tokens_out} tok · ${usage.cost_usd.toFixed(4)} ·{" "}
            {(usage.latency_ms / 1000).toFixed(1)}s
          </p>
        )}
      </aside>
    </div>
  );
}
