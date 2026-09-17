/**
 * The reconnecting reply controller, driven with hand-rolled fakes of the
 * two stream openers — no network, no React.
 */
import type { StreamEvent } from '@/api/ai';
import { ApiError } from '@/api/client';
import { createReplyStream } from '@/hooks/useReplyStream';

jest.mock('react-native', () => ({ AppState: { currentState: 'active', addEventListener: jest.fn() } }));

const mockStreamMessage = jest.fn();
const mockResumeStream = jest.fn();
jest.mock('@/api/ai', () => ({
  streamMessage: (...a: unknown[]) => mockStreamMessage(...a),
  resumeStream: (...a: unknown[]) => mockResumeStream(...a),
}));

class Fake {
  resolve!: (v: 'finished' | 'lost') => void;
  reject!: (e: unknown) => void;
  promise: Promise<'finished' | 'lost'>;
  abort = jest.fn();
  constructor(public onEvent: (ev: StreamEvent) => void) {
    this.promise = new Promise((res, rej) => { this.resolve = res; this.reject = rej; });
  }
}

// Drain pending microtasks (fake timers are on, so no real setTimeout here).
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

describe('createReplyStream', () => {
  beforeEach(() => { jest.useFakeTimers(); mockStreamMessage.mockReset(); mockResumeStream.mockReset(); });
  afterEach(() => jest.useRealTimers());

  test('a lost connection resumes from the events already seen', async () => {
    const first = new Fake(() => {});
    mockStreamMessage.mockImplementation((_c: string, _t: string, _m: string, onEvent: (ev: StreamEvent) => void) => {
      first.onEvent = onEvent; return { promise: first.promise, abort: first.abort };
    });
    const events: StreamEvent[] = [];
    const ctl = createReplyStream();
    ctl.send({ convId: 'c1', text: 'hi', model: 'flash', onEvent: (ev: StreamEvent) => events.push(ev), onGone: jest.fn() });
    first.onEvent({ type: 'delta', text: 'a' });
    first.onEvent({ type: 'delta', text: 'b' });

    const second = new Fake(() => {});
    mockResumeStream.mockImplementation((_c: string, from: number, onEvent: (ev: StreamEvent) => void) => {
      expect(from).toBe(2);
      second.onEvent = onEvent; return { promise: second.promise, abort: second.abort };
    });
    first.resolve('lost');
    await flush();
    jest.advanceTimersByTime(1000);         // first retry after 1s backoff
    await flush();
    expect(mockResumeStream).toHaveBeenCalledTimes(1);
    second.onEvent({ type: 'delta', text: 'c' });
    second.onEvent({ type: 'done', message: { role: 'assistant', content: 'abc' }, conversation: { id: 'c1', title: 't', model: 'm', updated_at: '', message_count: 2 } });
    second.resolve('finished');
    await flush();
    expect(events.map((e) => e.type)).toEqual(['delta', 'delta', 'delta', 'done']);
  });

  test('a 404 on resume hands the conversation back via onGone', async () => {
    const first = new Fake(() => {});
    mockStreamMessage.mockImplementation((_c: string, _t: string, _m: string, onEvent: (ev: StreamEvent) => void) => {
      first.onEvent = onEvent; return { promise: first.promise, abort: first.abort };
    });
    const gone = jest.fn();
    const ctl = createReplyStream();
    ctl.send({ convId: 'c2', text: 'hi', model: 'flash', onEvent: jest.fn(), onGone: gone });
    const second = new Fake(() => {});
    mockResumeStream.mockImplementation(() => ({ promise: second.promise, abort: second.abort }));
    first.resolve('lost');
    await flush();
    jest.advanceTimersByTime(1000);
    await flush();
    second.reject(new ApiError(404, 'gone'));
    await flush();
    expect(gone).toHaveBeenCalledWith('c2');
  });

  test('stop() aborts and never reconnects', async () => {
    const first = new Fake(() => {});
    mockStreamMessage.mockImplementation(() => ({ promise: first.promise, abort: first.abort }));
    const ctl = createReplyStream();
    ctl.send({ convId: 'c3', text: 'hi', model: 'flash', onEvent: jest.fn(), onGone: jest.fn() });
    ctl.stop();
    expect(first.abort).toHaveBeenCalled();
    first.resolve('lost');
    await flush();
    jest.advanceTimersByTime(5000);
    await flush();
    expect(mockResumeStream).not.toHaveBeenCalled();
  });
});
