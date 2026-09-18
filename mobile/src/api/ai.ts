/**
 * Client for the AI chat service (app/ai/* on the pipeline box), reached
 * at `EXPO_PUBLIC_AI_URL` — or, by default, the archive URL with its
 * `/reports` path swapped for `/ai` (both are `tailscale serve` paths on
 * the same host).
 *
 * Replies stream as server-sent events. React Native's fetch has no
 * ReadableStream, so the stream helpers use XMLHttpRequest and parse the
 * growing `responseText` on each progress event. Generation happens in a
 * server-side job that outlives the connection: if the app is suspended
 * mid-reply, `resumeStream` picks the same reply up where it stopped.
 */
import { APP_TOKEN_HEADER, ApiError, BASE_URL } from './client';
import { authHeaders } from './session';

const AI_URL = (
  process.env.EXPO_PUBLIC_AI_URL?.replace(/\/$/, '') ??
  BASE_URL.replace(/\/reports$/, '/ai')
);

export type ModelKey = 'flash' | 'pro' | 'claude';

export type ModelOption = { key: ModelKey; id: string; label: string; hint: string };

export type ChatUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  ts?: string;
  model?: string;
  companies?: string[];
  usage?: ChatUsage;
};

export type ConversationSummary = {
  id: string;
  title: string;
  model: string | null;
  updated_at: string;
  message_count: number;
};

export type StreamEvent =
  | { type: 'companies'; tickers: string[] }
  | { type: 'status'; text: string }
  | { type: 'delta'; text: string }
  | { type: 'done'; message: ChatMessage; conversation: ConversationSummary }
  | { type: 'error'; text: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${AI_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      cache: 'no-store',
      ...init,
      headers: { 'content-type': 'application/json', ...APP_TOKEN_HEADER, ...authHeaders(), ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(0, `Network error reaching ${url}: ${e}`);
  }
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText} at ${url}`);
  return (await res.json()) as T;
}

export const aiApi = {
  /** Models the server offers right now (Claude only when its key is configured). */
  listModels: () => req<{ models: ModelOption[] }>('/models').then((r) => r.models),
  listConversations: () =>
    req<{ conversations: ConversationSummary[] }>('/conversations').then((r) => r.conversations),
  createConversation: (model: ModelKey) =>
    req<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ model }) }),
  getConversation: (id: string) => req<Conversation>(`/conversations/${encodeURIComponent(id)}`),
  deleteConversation: (id: string) =>
    req<{ deleted: string }>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

export type Conversation = ConversationSummary & { messages: ChatMessage[]; pending?: boolean };

export type StreamOutcome = 'finished' | 'lost';

/**
 * Open an SSE connection and feed each event to `onEvent`. The promise
 * resolves `'finished'` when a terminal `done` / `error` event arrived and
 * `'lost'` when the transport ended before one (the OS suspended the app,
 * the socket dropped, or `abort()` was called) — the server keeps
 * generating either way, so the caller can `resumeStream` from the number
 * of events it has already seen. Rejects only on an HTTP error status.
 */
function openStream(
  method: 'POST' | 'GET',
  url: string,
  body: string | null,
  onEvent: (ev: StreamEvent) => void,
): { promise: Promise<StreamOutcome>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  let consumed = 0;
  let terminal = false;

  const drain = () => {
    const text = xhr.responseText ?? '';
    // Only parse complete events (terminated by a blank line).
    let boundary = text.indexOf('\n\n', consumed);
    while (boundary !== -1) {
      const raw = text.slice(consumed, boundary);
      consumed = boundary + 2;
      const line = raw.split('\n').find((l) => l.startsWith('data:'));
      if (line) {
        try {
          const ev = JSON.parse(line.slice(5)) as StreamEvent;
          if (ev.type === 'done' || ev.type === 'error') terminal = true;
          onEvent(ev);
        } catch {
          // malformed frame — skip
        }
      }
      boundary = text.indexOf('\n\n', consumed);
    }
  };

  const promise = new Promise<StreamOutcome>((resolve, reject) => {
    xhr.open(method, url);
    xhr.setRequestHeader('content-type', 'application/json');
    xhr.setRequestHeader('accept', 'text/event-stream');
    for (const [k, v] of Object.entries({ ...APP_TOKEN_HEADER, ...authHeaders() })) xhr.setRequestHeader(k, v);
    xhr.onprogress = drain;
    xhr.onload = () => {
      drain();
      if (xhr.status >= 200 && xhr.status < 300) resolve(terminal ? 'finished' : 'lost');
      else reject(new ApiError(xhr.status, `${xhr.status} from AI service`));
    };
    xhr.onerror = () => { drain(); resolve(terminal ? 'finished' : 'lost'); };
    xhr.ontimeout = () => { drain(); resolve(terminal ? 'finished' : 'lost'); };
    xhr.onabort = () => { drain(); resolve(terminal ? 'finished' : 'lost'); };
    xhr.send(body);
  });

  return { promise, abort: () => xhr.abort() };
}

/** POST a user message and stream the reply from event 0. */
export function streamMessage(
  conversationId: string,
  content: string,
  model: ModelKey,
  onEvent: (ev: StreamEvent) => void,
) {
  return openStream(
    'POST',
    `${AI_URL}/conversations/${encodeURIComponent(conversationId)}/messages`,
    JSON.stringify({ content, model }),
    onEvent,
  );
}

/**
 * Re-attach to a reply the server is still generating (or finished within
 * the last few minutes), replaying events from index `from`. Rejects with
 * ApiError(404) when nothing is buffered any more — reload the conversation
 * instead, the stored reply is there if it ever finished.
 */
export function resumeStream(
  conversationId: string,
  from: number,
  onEvent: (ev: StreamEvent) => void,
) {
  return openStream(
    'GET',
    `${AI_URL}/conversations/${encodeURIComponent(conversationId)}/stream?from=${from}`,
    null,
    onEvent,
  );
}

export { AI_URL };
