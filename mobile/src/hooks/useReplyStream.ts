/**
 * Drives one streamed AI reply and keeps it alive across app suspensions.
 *
 * The server generates the reply in a job that outlives the HTTP
 * connection, so when iOS/Android kill the socket (backgrounding, a
 * network blip) we simply re-attach from the number of events already
 * seen — immediately if the app is in the foreground, otherwise as soon
 * as it comes back. If the server no longer has the job buffered (404),
 * `onGone` fires so the screen reloads the stored conversation, which
 * holds the full reply if it ever finished.
 */
import { useEffect, useMemo } from 'react';
import { AppState } from 'react-native';

import { resumeStream, streamMessage, type ModelKey, type StreamEvent } from '../api/ai';
import { ApiError } from '../api/client';

type Live = {
  convId: string;
  seen: number;                       // events consumed so far = resume index
  inFlight: boolean;
  stopped: boolean;                   // the user hit Stop — don't reconnect
  retries: number;
  onEvent: (ev: StreamEvent) => void;
  onGone: (convId: string) => void;
  abort: () => void;
};

type Handlers = {
  onEvent: (ev: StreamEvent) => void;
  onGone: (convId: string) => void;
};

type Opener = () => { promise: Promise<'finished' | 'lost'>; abort: () => void };

const MAX_RETRIES = 5;

export function createReplyStream() {
  let live: Live | null = null;

  const finish = (l: Live) => {
    if (live === l) live = null;
  };

  const resume = (l: Live) => {
    if (live !== l || l.stopped || l.inFlight) return;
    if (l.retries >= MAX_RETRIES) {
      finish(l);
      l.onEvent({ type: 'error', text: 'Lost the connection to the AI service.' });
      return;
    }
    l.retries += 1;
    void attach(l, () => resumeStream(l.convId, l.seen, (ev) => { l.seen += 1; l.onEvent(ev); }));
  };

  const attach = async (l: Live, open: Opener) => {
    const { promise, abort } = open();
    l.abort = abort;
    l.inFlight = true;
    let outcome: 'finished' | 'lost';
    try {
      outcome = await promise;
    } catch (e) {
      l.inFlight = false;
      if (live !== l) return;
      finish(l);
      if (e instanceof ApiError && e.status === 404) l.onGone(l.convId);
      else l.onEvent({ type: 'error', text: String((e as Error).message ?? e) });
      return;
    }
    l.inFlight = false;
    if (live !== l) return;
    if (outcome === 'finished' || l.stopped) { finish(l); return; }
    // Connection lost mid-reply. Reconnect now if we're in the foreground;
    // `onAppActive` handles the background case.
    if (AppState.currentState === 'active') {
      setTimeout(() => resume(l), Math.min(1000 * 2 ** l.retries, 15000));
    }
  };

  const begin = (convId: string, handlers: Handlers): Live => {
    live?.abort();
    const l: Live = {
      convId, seen: 0, inFlight: false, stopped: false, retries: 0,
      onEvent: handlers.onEvent, onGone: handlers.onGone, abort: () => {},
    };
    live = l;
    return l;
  };

  return {
    /** Send a message and stream its reply; supersedes any reply in flight. */
    send(args: { convId: string; text: string; model: ModelKey } & Handlers) {
      const l = begin(args.convId, args);
      void attach(l, () => streamMessage(l.convId, args.text, args.model, (ev) => { l.seen += 1; l.onEvent(ev); }));
    },
    /** Attach to a reply the server is already generating for `convId`
     *  (a conversation opened with `pending: true`), replaying from the start. */
    follow(args: { convId: string } & Handlers) {
      const l = begin(args.convId, args);
      void attach(l, () => resumeStream(l.convId, 0, (ev) => { l.seen += 1; l.onEvent(ev); }));
    },
    /** Stop listening (the server still finishes and stores the reply). */
    stop() {
      const l = live;
      if (!l) return;
      l.stopped = true;
      l.abort();
      finish(l);
    },
    /** The app came back to the foreground: re-attach if a reply is dangling. */
    onAppActive() {
      const l = live;
      if (l && !l.inFlight) {
        l.retries = 0;
        resume(l);
      }
    },
  };
}

export function useReplyStream() {
  const ctl = useMemo(createReplyStream, []);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => { if (s === 'active') ctl.onAppActive(); });
    return () => { sub.remove(); ctl.stop(); };
  }, [ctl]);
  return ctl;
}
