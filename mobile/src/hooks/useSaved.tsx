/**
 * The user's saved companies as NAMED LISTS (the "Saved" tab and the
 * bookmark on company pages).
 *
 * Signed in: the account's lists on the box are the source of truth; a
 * copy is cached in AsyncStorage so the tab renders instantly and offline,
 * and every change is applied optimistically then sent to the server.
 * Signed out: one local list ("Saved") that is pushed into the account's
 * default list at the next sign-in.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { watchlistApi, type Watchlist } from '@/api/watchlist';
import { useAuth } from '@/hooks/useAuth';

const KEY = 'saved_lists_v2';
const LEGACY_KEY = 'saved_tickers_v1';
const LOCAL_ID = -1;

type Saved = {
  lists: Watchlist[];
  /** true once storage (and, when signed in, the server) has been read. */
  ready: boolean;
  /** Every saved ticker across lists, newest first, deduped. */
  tickers: string[];
  /** Lists containing the symbol. */
  listsFor: (symbol: string) => Watchlist[];
  isSaved: (symbol: string) => boolean;
  /** Add to a list (default: the first list). */
  add: (symbol: string, listId?: number) => void;
  /** Remove from a list (default: every list). */
  remove: (symbol: string, listId?: number) => void;
  /** Toggle membership in the first list (the bookmark's quick action). */
  toggle: (symbol: string) => void;
  createList: (name: string) => Promise<Watchlist | null>;
  renameList: (id: number, name: string) => Promise<void>;
  deleteList: (id: number) => Promise<void>;
  refresh: () => Promise<void>;
};

const SavedContext = createContext<Saved | null>(null);

/** One entry per list id (a stale cache plus a server copy must never show a list twice). */
function dedupe(lists: Watchlist[]): Watchlist[] {
  const seen = new Set<number>();
  return lists.filter((l) => (seen.has(l.id) ? false : (seen.add(l.id), true)));
}

function persist(lists: Watchlist[]) {
  AsyncStorage.setItem(KEY, JSON.stringify(lists)).catch(() => {});
}

export function SavedProvider({ children }: { children: ReactNode }) {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [ready, setReady] = useState(false);
  const { user } = useAuth();
  const signedIn = user !== null;
  const listsRef = useRef(lists);
  listsRef.current = lists;

  // Storage first (instant, offline), with a one-time upgrade of the old single list.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        let parsed: Watchlist[] = raw ? JSON.parse(raw) : [];
        if (!parsed.length) {
          const legacy = await AsyncStorage.getItem(LEGACY_KEY);
          const tickers = legacy ? (JSON.parse(legacy) as string[]) : [];
          parsed = [{ id: LOCAL_ID, name: 'Saved', position: 0, tickers }];
        }
        if (!cancelled) setLists(dedupe(parsed));
      } catch {
        if (!cancelled) setLists([{ id: LOCAL_ID, name: 'Saved', position: 0, tickers: [] }]);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const refresh = useCallback(async () => {
    if (!signedIn) return;
    try {
      const server = dedupe(await watchlistApi.lists());
      setLists(server);
      persist(server);
    } catch {
      // offline: keep the cached copy
    }
  }, [signedIn]);

  // Sign-in: push any local-only list into the account's default list, then adopt the server's lists.
  useEffect(() => {
    if (!signedIn || !ready) return;
    (async () => {
      try {
        const local = listsRef.current.find((l) => l.id === LOCAL_ID);
        let server = await watchlistApi.lists();
        if (local?.tickers.length && server.length) {
          await watchlistApi.add(server[0].id, local.tickers);
          server = await watchlistApi.lists();
        }
        setLists(dedupe(server));
        persist(dedupe(server));
      } catch {
        // offline — the next change retries
      }
    })();
  }, [signedIn, ready]);

  const update = useCallback((fn: (prev: Watchlist[]) => Watchlist[]) => {
    setLists((prev) => { const next = dedupe(fn(prev)); persist(next); return next; });
  }, []);

  const add = useCallback((symbol: string, listId?: number) => {
    const sym = symbol.toUpperCase();
    const target = listId ?? listsRef.current[0]?.id;
    if (target == null) return;
    update((prev) => prev.map((l) => (l.id === target && !l.tickers.includes(sym) ? { ...l, tickers: [sym, ...l.tickers] } : l)));
    if (signedIn && target !== LOCAL_ID) watchlistApi.add(target, [sym]).catch(() => {});
  }, [signedIn, update]);

  const remove = useCallback((symbol: string, listId?: number) => {
    const sym = symbol.toUpperCase();
    const targets = listId != null ? [listId] : listsRef.current.filter((l) => l.tickers.includes(sym)).map((l) => l.id);
    update((prev) => prev.map((l) => (targets.includes(l.id) ? { ...l, tickers: l.tickers.filter((t) => t !== sym) } : l)));
    if (signedIn) for (const id of targets) if (id !== LOCAL_ID) watchlistApi.removeTicker(id, sym).catch(() => {});
  }, [signedIn, update]);

  const createList = useCallback(async (name: string) => {
    if (!signedIn) return null;
    const created = await watchlistApi.create(name);
    update((prev) => [...prev, created]);
    return created;
  }, [signedIn, update]);

  const renameList = useCallback(async (id: number, name: string) => {
    if (!signedIn || id === LOCAL_ID) return;
    const renamed = await watchlistApi.rename(id, name);
    update((prev) => prev.map((l) => (l.id === id ? renamed : l)));
  }, [signedIn, update]);

  const deleteList = useCallback(async (id: number) => {
    if (!signedIn || id === LOCAL_ID) return;
    await watchlistApi.remove(id);
    update((prev) => prev.filter((l) => l.id !== id));
  }, [signedIn, update]);

  const value = useMemo<Saved>(() => {
    const tickers = Array.from(new Set(lists.flatMap((l) => l.tickers)));
    const listsFor = (symbol: string) => lists.filter((l) => l.tickers.includes(symbol.toUpperCase()));
    return {
      lists, ready, tickers, listsFor,
      isSaved: (symbol) => listsFor(symbol).length > 0,
      add, remove,
      toggle: (symbol) => (lists[0]?.tickers.includes(symbol.toUpperCase()) ? remove(symbol, lists[0].id) : add(symbol, lists[0]?.id)),
      createList, renameList, deleteList, refresh,
    };
  }, [lists, ready, add, remove, createList, renameList, deleteList, refresh]);

  return <SavedContext.Provider value={value}>{children}</SavedContext.Provider>;
}

export function useSaved(): Saved {
  const ctx = useContext(SavedContext);
  if (!ctx) throw new Error('useSaved must be used inside SavedProvider');
  return ctx;
}
