/**
 * Client for the AI chat service (app/ai/* on the pipeline box), reached
 * at `EXPO_PUBLIC_AI_URL` — or, by default, the archive URL with its
 * `/reports` path swapped for `/ai` (both are `tailscale serve` paths on
 * the same host).
 *
 * Replies stream as server-sent events. React Native's fetch has no
 * ReadableStream, so `streamMessage` uses XMLHttpRequest and parses the
 * growing `responseText` on each progress event.
 */
import { ApiError, BASE_URL } from './client';

const AI_URL = (
  process.env.EXPO_PUBLIC_AI_URL?.replace(/\/$/, '') ??
  BASE_URL.replace(/\/reports$/, '/ai')
);

export type ModelKey = 'flash' | 'pro';

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

export type Conversation = ConversationSummary & { messages: ChatMessage[] };

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
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(0, `Network error reaching ${url}: ${e}`);
  }
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText} at ${url}`);
  return (await res.json()) as T;
}

export const aiApi = {
  listConversations: () =>
    req<{ conversations: ConversationSummary[] }>('/conversations').then((r) => r.conversations),
  createConversation: (model: ModelKey) =>
    req<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ model }) }),
  getConversation: (id: string) => req<Conversation>(`/conversations/${encodeURIComponent(id)}`),
  deleteConversation: (id: string) =>
    req<{ deleted: string }>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

/**
 * POST a user message and stream the reply. `onEvent` fires per SSE event;
 * the returned function aborts the request. Resolves when the stream ends
 * (after `done` or `error`), rejects only on transport failure.
 */
export function streamMessage(
  conversationId: string,
  content: string,
  model: ModelKey,
  onEvent: (ev: StreamEvent) => void,
): { promise: Promise<void>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  let consumed = 0;

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
          onEvent(JSON.parse(line.slice(5)) as StreamEvent);
        } catch {
          // malformed frame — skip
        }
      }
      boundary = text.indexOf('\n\n', consumed);
    }
  };

  const promise = new Promise<void>((resolve, reject) => {
    xhr.open('POST', `${AI_URL}/conversations/${encodeURIComponent(conversationId)}/messages`);
    xhr.setRequestHeader('content-type', 'application/json');
    xhr.setRequestHeader('accept', 'text/event-stream');
    xhr.onprogress = drain;
    xhr.onload = () => {
      drain();
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new ApiError(xhr.status, `${xhr.status} from AI service`));
    };
    xhr.onerror = () => reject(new ApiError(0, 'Network error reaching the AI service'));
    xhr.onabort = () => resolve();
    xhr.send(JSON.stringify({ content, model }));
  });

  return { promise, abort: () => xhr.abort() };
}

export { AI_URL };
