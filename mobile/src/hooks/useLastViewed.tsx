/**
 * Remembers the last industry and last company the user looked at, so the
 * home screen can highlight "where you left off" in the industry list and an
 * industry screen can highlight the company you last opened.
 *
 * Persisted across app launches via AsyncStorage. Highlighting is best-effort:
 * any storage error is swallowed (the app still works, it just won't restore
 * the highlight). State is exposed through a context so a write on the ticker
 * screen re-highlights the home screen without a manual refresh.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

const KEY_INDUSTRY = 'valueland:lastIndustrySlug';
const KEY_COMPANY = 'valueland:lastCompanyTicker';
const KEY_BATCH = 'valueland:lastBatchDate';

type LastViewed = {
  /** Slug of the last industry opened (matches IndustrySummary.slug). */
  lastIndustry: string | null;
  /** Ticker of the last company opened (upper-case, matches TickerRow.ticker). */
  lastCompany: string | null;
  /** Date string of the last batch/digest opened (matches RecentDigest.date). */
  lastBatch: string | null;
  setLastIndustry: (slug: string) => void;
  setLastCompany: (ticker: string) => void;
  setLastBatch: (date: string) => void;
};

const LastViewedContext = createContext<LastViewed | null>(null);

export function LastViewedProvider({ children }: { children: ReactNode }) {
  const [lastIndustry, setIndustry] = useState<string | null>(null);
  const [lastCompany, setCompany] = useState<string | null>(null);
  const [lastBatch, setBatch] = useState<string | null>(null);

  // Hydrate once on mount.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const pairs = await AsyncStorage.multiGet([KEY_INDUSTRY, KEY_COMPANY, KEY_BATCH]);
        if (!alive) return;
        const map = Object.fromEntries(pairs);
        if (map[KEY_INDUSTRY]) setIndustry(map[KEY_INDUSTRY]);
        if (map[KEY_COMPANY]) setCompany(map[KEY_COMPANY]);
        if (map[KEY_BATCH]) setBatch(map[KEY_BATCH]);
      } catch {
        // best-effort: leave highlights off if storage is unavailable
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const setLastIndustry = useCallback((slug: string) => {
    setIndustry((prev) => (prev === slug ? prev : slug));
    AsyncStorage.setItem(KEY_INDUSTRY, slug).catch(() => {});
  }, []);

  const setLastCompany = useCallback((ticker: string) => {
    const t = ticker.toUpperCase();
    setCompany((prev) => (prev === t ? prev : t));
    AsyncStorage.setItem(KEY_COMPANY, t).catch(() => {});
  }, []);

  const setLastBatch = useCallback((date: string) => {
    setBatch((prev) => (prev === date ? prev : date));
    AsyncStorage.setItem(KEY_BATCH, date).catch(() => {});
  }, []);

  return (
    <LastViewedContext.Provider
      value={{ lastIndustry, lastCompany, lastBatch, setLastIndustry, setLastCompany, setLastBatch }}
    >
      {children}
    </LastViewedContext.Provider>
  );
}

export function useLastViewed(): LastViewed {
  const ctx = useContext(LastViewedContext);
  if (!ctx) {
    throw new Error('useLastViewed must be used within a LastViewedProvider');
  }
  return ctx;
}
