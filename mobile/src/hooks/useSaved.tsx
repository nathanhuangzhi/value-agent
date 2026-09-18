/**
 * The user's saved companies (the "Saved" tab). An ordered list of ticker
 * symbols, newest first, persisted on-device via AsyncStorage — the
 * archive is a static site, so there's nowhere else for it to live.
 *
 * Same shape as useLastViewed: a context provider at the root, a hook
 * anywhere below it. Writes are optimistic (state first, storage after).
 *
 * When signed in, every change is also mirrored to the account's
 * /watchlist on the box (best effort, no UI on failure) so the daily run
 * fetches data for saved companies. On sign-in the phone's list is pushed
 * up and the account's list merged down, so a second device sees the same
 * companies.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { watchlistApi } from '@/api/watchlist';
import { useAuth } from '@/hooks/useAuth';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

const KEY = 'saved_tickers_v1';

type Saved = {
  /** Upper-cased symbols, most recently saved first. */
  tickers: string[];
  /** true once AsyncStorage has been read (so an empty list isn't a flash). */
  ready: boolean;
  isSaved: (symbol: string) => boolean;
  add: (symbol: string) => void;
  remove: (symbol: string) => void;
  toggle: (symbol: string) => void;
};

const SavedContext = createContext<Saved | null>(null);

export function SavedProvider({ children }: { children: ReactNode }) {
  const [tickers, setTickers] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const { user } = useAuth();
  const signedIn = user !== null;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        const parsed = raw ? (JSON.parse(raw) as unknown) : [];
        if (!cancelled && Array.isArray(parsed)) {
          const list = parsed.filter((t): t is string => typeof t === 'string');
          setTickers(list);
        }
      } catch {
        // Corrupt / unavailable storage: start empty, keep the app usable.
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Sign-in (or launch while signed in): push the local list up, merge the
  // account's list down.
  useEffect(() => {
    if (!signedIn || !ready) return;
    let cancelled = false;
    (async () => {
      try {
        const server = tickers.length ? await watchlistApi.add(tickers) : await watchlistApi.get();
        if (cancelled) return;
        setTickers((prev) => {
          const missing = server.tickers.filter((t) => !prev.includes(t));
          if (!missing.length) return prev;
          const next = [...prev, ...missing];
          AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
          return next;
        });
      } catch {
        // offline or signed out meanwhile — the next change retries
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn, ready]);

  const add = useCallback((symbol: string) => {
    const sym = symbol.toUpperCase();
    setTickers((prev) => {
      if (prev.includes(sym)) return prev;
      const next = [sym, ...prev];
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
      if (signedIn) watchlistApi.add([sym]).catch(() => {});
      return next;
    });
  }, [signedIn]);

  const remove = useCallback((symbol: string) => {
    const sym = symbol.toUpperCase();
    setTickers((prev) => {
      if (!prev.includes(sym)) return prev;
      const next = prev.filter((t) => t !== sym);
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
      if (signedIn) watchlistApi.remove(sym).catch(() => {});
      return next;
    });
  }, [signedIn]);

  const value = useMemo<Saved>(
    () => ({
      tickers,
      ready,
      isSaved: (symbol) => tickers.includes(symbol.toUpperCase()),
      add,
      remove,
      toggle: (symbol) => (tickers.includes(symbol.toUpperCase()) ? remove(symbol) : add(symbol)),
    }),
    [tickers, ready, add, remove],
  );

  return <SavedContext.Provider value={value}>{children}</SavedContext.Provider>;
}

export function useSaved(): Saved {
  const ctx = useContext(SavedContext);
  if (!ctx) throw new Error('useSaved must be used inside <SavedProvider>');
  return ctx;
}
