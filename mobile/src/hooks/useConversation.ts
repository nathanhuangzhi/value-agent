/**
 * One conversation's state and actions, shared by the AI tab and the
 * company-page chat: messages, the reply being streamed, errors, and
 * open / send / stop / reset. Streaming (with reconnects) is delegated
 * to useReplyStream; persistence to the server via aiApi.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useRef, useState } from 'react';

import { aiApi, type ChatMessage, type ModelKey, type StreamEvent } from '../api/ai';
import { useReplyStream } from './useReplyStream';

export const LAST_CONV_KEY = 'ai_last_conversation_v1';   // the chat to reopen on next launch

export type Streaming = { status: string | null; text: string; companies: string[] };

export function useConversation(opts: { onChanged?: () => void } = {}) {
  const [convId, setConvId] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reply = useReplyStream();
  const onChanged = useRef(opts.onChanged);
  useEffect(() => { onChanged.current = opts.onChanged; });

  const fail = (e: unknown) => setError(String((e as Error).message ?? e));

  // Events of a streamed reply, whether freshly sent or re-attached.
  const handlers = useCallback((id: string) => ({
    onEvent: (ev: StreamEvent) => {
      switch (ev.type) {
        case 'companies':
          setStreaming((s) => s && { ...s, companies: ev.tickers, status: `Reading ${ev.tickers.join(', ')}…` });
          break;
        case 'status':
          setStreaming((s) => s && { ...s, status: ev.text });
          break;
        case 'delta':
          setStreaming((s) => s && { ...s, status: null, text: s.text + ev.text });
          break;
        case 'done':
          setMessages((m) => [...m, ev.message]);
          setTitle(ev.conversation.title);
          setStreaming(null);
          onChanged.current?.();
          break;
        case 'error':
          setError(ev.text);
          setStreaming(null);
          break;
      }
    },
    // The server no longer has the live reply buffered: the stored
    // conversation holds it in full if it finished.
    onGone: (cid: string) => {
      if (cid !== id) return;
      aiApi.getConversation(cid)
        .then((conv) => { setMessages(conv.messages); setTitle(conv.title); onChanged.current?.(); })
        .catch(fail)
        .finally(() => setStreaming(null));
    },
  }), []);

  /** Load a stored conversation; keep following its reply if one is still being written. */
  const open = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const conv = await aiApi.getConversation(id);
      reply.stop();
      setStreaming(null);
      setConvId(conv.id);
      setTitle(conv.title);
      setMessages(conv.messages);
      setError(null);
      AsyncStorage.setItem(LAST_CONV_KEY, conv.id).catch(() => {});
      if (conv.pending) {
        setStreaming({ status: 'Thinking…', text: '', companies: [] });
        reply.follow({ convId: conv.id, ...handlers(conv.id) });
      }
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  }, [reply, handlers]);

  /** Blank thread. `forget` also clears the "reopen on launch" pointer. */
  const reset = useCallback((forget = false) => {
    reply.stop();
    setStreaming(null);
    setConvId(null);
    setTitle(null);
    setMessages([]);
    setError(null);
    if (forget) AsyncStorage.removeItem(LAST_CONV_KEY).catch(() => {});
  }, [reply]);

  /** Send `text`; creates the conversation on first use. Returns false if nothing was sent. */
  const send = useCallback(async (text: string, model: ModelKey): Promise<boolean> => {
    if (!text.trim() || streaming) return false;
    setError(null);
    let id = convId;
    if (!id) {
      try {
        const conv = await aiApi.createConversation(model);
        id = conv.id;
        setConvId(id);
        setTitle(conv.title);
      } catch (e) {
        fail(e);
        return false;
      }
    }
    AsyncStorage.setItem(LAST_CONV_KEY, id).catch(() => {});
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setStreaming({ status: 'Thinking…', text: '', companies: [] });
    reply.send({ convId: id, text, model, ...handlers(id) });
    return true;
  }, [convId, streaming, reply, handlers]);

  /** Stop listening; what arrived so far stays as a local turn. The server
   *  still finishes and stores the full reply. */
  const stop = useCallback(() => {
    reply.stop();
    const partial = streaming?.text ?? '';
    setStreaming(null);
    if (partial) setMessages((m) => [...m, { role: 'assistant', content: partial + '\n\n_(stopped)_' }]);
  }, [reply, streaming]);

  return { convId, title, messages, streaming, error, loading, open, reset, send, stop, setError };
}
