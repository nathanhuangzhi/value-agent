/**
 * The user's saved companies (the "Saved" tab). An ordered list of ticker
 * symbols, newest first, persisted on-device via AsyncStorage — the
 * archive is a static site, so there's nowhere else for it to live.
 *
 * Same shape as useLastViewed: a context provider at the root, a hook
 * anywhere below it. Writes are optimistic (state first, storage after).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        const parsed = raw ? (JSON.parse(raw) as unknown) : [];
        if (!cancelled && Array.isArray(parsed)) {
          setTickers(parsed.filter((t): t is string => typeof t === 'string'));
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

  const add = useCallback((symbol: string) => {
    const sym = symbol.toUpperCase();
    setTickers((prev) => {
      if (prev.includes(sym)) return prev;
      const next = [sym, ...prev];
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, []);

  const remove = useCallback((symbol: string) => {
    const sym = symbol.toUpperCase();
    setTickers((prev) => {
      if (!prev.includes(sym)) return prev;
      const next = prev.filter((t) => t !== sym);
      AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, []);

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
