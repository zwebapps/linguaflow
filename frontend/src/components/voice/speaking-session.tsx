import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceCanvas } from "@/components/voice/voice-canvas";
import { ErrorAlert } from "@/components/shared/error-alert";
import { Spinner } from "@/components/shared/spinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { playSpeakingAudio, primeSpeechVoices, streamSpeakingTurn } from "@/lib/speaking-stream";
import type {
  CefrLevel,
  SpeakingScenario,
  SpeakingStreamScores,
  SpeakingStreamUsage,
} from "@/lib/types";

type Phase = "idle" | "recording" | "sending";

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
    initialScenarioId ?? scenarios[0]?.id ?? "smalltalk",
  );
  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios[0];

  const [phase, setPhase] = useState<Phase>("idle");
  const [muted, setMuted] = useState(false);
  const [level, setLevel] = useState(0);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState<string | null>(null);
  const [assistantReply, setAssistantReply] = useState("");
  const [scores, setScores] = useState<SpeakingStreamScores | null>(null);
  const [usage, setUsage] = useState<SpeakingStreamUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [micDenied, setMicDenied] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number>(0);
  const abortRef = useRef<AbortController | null>(null);

  const stopMeter = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    setLevel(0);
  }, []);

  const startMeter = useCallback((stream: MediaStream) => {
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i];
      setLevel(Math.min(100, (sum / data.length / 255) * 140));
      rafRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  const releaseStream = useCallback(() => {
    stopMeter();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, [stopMeter]);

  useEffect(
    () => () => {
      releaseStream();
      abortRef.current?.abort();
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
  }, [scenarioId]);

  const speakOpening = useCallback(() => {
    if (!scenario?.opening || muted) return;
    playSpeakingAudio(
      { use_browser_tts: true, text: scenario.opening, lang: "de-DE", data_uri: null },
      muted,
    );
  }, [scenario?.opening, muted]);

  async function sendRecording(blob: Blob) {
    setPhase("sending");
    setStatusLabel("Uploading…");
    setAssistantReply("");
    setScores(null);
    setError(null);

    const form = new FormData();
    form.append("audio", blob, "turn.webm");
    form.append("scenario", scenarioId);
    form.append("cefr_level", cefrLevel);
    form.append("want_audio", "true");
    if (threadId) form.append("thread_id", threadId);

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      await streamSpeakingTurn(
        form,
        {
          onStart: (d) => setThreadId(d.thread_id),
          onStatus: (d) => setStatusLabel(d.label),
          onTranscript: (d) => setLastTranscript(d.text),
          onToken: (d) => setAssistantReply((prev) => prev + d.text),
          onScores: (d) => setScores(d),
          onAudio: (d) => playSpeakingAudio(d, muted),
          onUsage: (d) => setUsage(d),
          onDone: () => {
            setStatusLabel(null);
            setPhase("idle");
          },
          onError: (d) => {
            setError(d.message);
            setStatusLabel(null);
            setPhase("idle");
          },
        },
        ac.signal,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Speaking turn failed");
      setPhase("idle");
      setStatusLabel(null);
    }
  }

  async function startRecording() {
    setError(null);
    setMicDenied(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      startMeter(stream);
      chunksRef.current = [];
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : undefined;
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = rec;
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        releaseStream();
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size > 0) void sendRecording(blob);
        else {
          setPhase("idle");
          setError("No audio captured — hold the button while you speak.");
        }
      };
      rec.start();
      setPhase("recording");
    } catch {
      setMicDenied(true);
      setPhase("idle");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    else setPhase("idle");
  }

  const busy = phase === "sending";
  const recording = phase === "recording";

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Select value={scenarioId} onValueChange={setScenarioId} disabled={busy || recording}>
            <SelectTrigger className="w-full max-w-xs rounded-xl">
              <SelectValue placeholder="Scenario" />
            </SelectTrigger>
            <SelectContent>
              {scenarios.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="rounded-xl"
            onClick={speakOpening}
            disabled={muted}
          >
            Hear opening
          </Button>
        </div>

        {scenario && (
          <p className="rounded-xl border border-border bg-card/80 px-4 py-3 text-sm italic text-muted-foreground">
            „{scenario.opening}&ldquo;
          </p>
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
          listening={recording}
          level={level}
          muted={muted}
          busy={busy}
          statusLabel={statusLabel}
          onToggleMute={() => setMuted((m) => !m)}
          onRecordStart={() => void startRecording()}
          onRecordStop={stopRecording}
        />

        <p className="text-center text-xs text-muted-foreground">
          Push and hold to speak · release to send · transcribed and answered in your target language
        </p>
      </div>

      <aside className="space-y-4">
        <div className="neo-card panel rounded-xl p-4">
          <p className="label-mono mb-2">Your last turn</p>
          {busy && !lastTranscript && <Spinner label={statusLabel ?? "Processing…"} />}
          {lastTranscript ? (
            <p className="text-sm">{lastTranscript}</p>
          ) : (
            !busy && <p className="text-sm text-muted-foreground">Record a turn to see your transcript.</p>
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
