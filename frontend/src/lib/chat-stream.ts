import { API_BASE } from "./env";
import { getAccessToken } from "./auth-store";
import { ApiError } from "./api";
import type {
  ApiErrorBody,
  ChatRequest,
  ChatStreamDone,
  ChatStreamError,
  ChatStreamSources,
  ChatStreamStart,
  ChatStreamStatus,
  ChatStreamToken,
  ChatStreamToolCall,
  ChatStreamToolResult,
  ChatStreamUsage,
} from "./types";

export type ChatStreamHandlers = {
  onStart: (d: ChatStreamStart) => void;
  onStatus: (d: ChatStreamStatus) => void;
  onToolCall: (d: ChatStreamToolCall) => void;
  onToolResult: (d: ChatStreamToolResult) => void;
  onSources: (d: ChatStreamSources) => void;
  onToken: (d: ChatStreamToken) => void;
  onUsage: (d: ChatStreamUsage) => void;
  onDone: (d: ChatStreamDone) => void;
  onError: (d: ChatStreamError) => void;
};

async function toApiError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody = {
    error: { code: "internal_error", message: res.statusText || "Chat failed" },
  };
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* empty */
  }
  return new ApiError(res.status, body);
}

export async function streamChat(
  body: ChatRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  const dispatch = (ev: string, raw: string) => {
    const d = JSON.parse(raw) as Record<string, unknown>;
    const map: Record<string, (payload: never) => void> = {
      start: handlers.onStart as (p: never) => void,
      status: handlers.onStatus as (p: never) => void,
      tool_call: handlers.onToolCall as (p: never) => void,
      tool_result: handlers.onToolResult as (p: never) => void,
      sources: handlers.onSources as (p: never) => void,
      token: handlers.onToken as (p: never) => void,
      usage: handlers.onUsage as (p: never) => void,
      done: handlers.onDone as (p: never) => void,
      error: handlers.onError as (p: never) => void,
    };
    map[ev]?.(d as never);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    // Normalise CRLF first. The server emits spec-compliant \r\n line endings, so
    // splitting on "\n\n" alone never matches a frame boundary — every event was
    // silently dropped and the stream looked dead.
    buf += value.replace(/\r\n/g, "\n");
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const frame of frames) {
      const ev = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim();
      const raw = frame.match(/^data:\s*([\s\S]+)$/m)?.[1]?.trim();
      if (!ev || !raw) continue;
      dispatch(ev, raw);
    }
  }
}
