/**
 * Reusable data hooks built on top of the `api` client. Each hook returns
 * `{ data, loading, error, refresh }` — a small surface that's the same
 * across endpoints, so screens look identical regardless of which one
 * they're fetching from.
 *
 * The hooks deliberately don't use react-query / SWR yet — the app is
 * small enough that the extra dependency isn't justified. Migrate later
 * if you add caching across screens or background refresh.
 *
 * Ticker-detail + price-history use a small in-memory SWR cache: a tap
 * on a previously-visited ticker renders instantly from cache, then a
 * background refetch revalidates. Sidebar prefetch (see
 * `prefetchTickerDetail`) warms the cache ahead of the first tap.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from './client';
import type {
  DigestResponse,
  IndustryDetailResponse,
  IndustryListResponse,
  PriceHistoryResponse,
  RecentDigestsResponse,
  TickerDetail,
} from './types';

type Async<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetcher());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

// ---------------------------------------------------------------------------
// SWR caches — module-level so they survive component unmounts. Keyed by
// upper-cased symbol so "qdel" and "QDEL" share a cache entry. We dedupe
// in-flight fetches via the `inflight` maps so a `useTickerDetail` mount
// concurrent with a `prefetchTickerDetail` call only hits the API once.
// ---------------------------------------------------------------------------
const tickerCache = new Map<string, TickerDetail>();
const tickerInflight = new Map<string, Promise<TickerDetail>>();
const priceCache = new Map<string, PriceHistoryResponse>();
const priceInflight = new Map<string, Promise<PriceHistoryResponse>>();
const industryCache = new Map<string, IndustryDetailResponse>();
const industryInflight = new Map<string, Promise<IndustryDetailResponse>>();

function fetchTicker(symbol: string): Promise<TickerDetail> {
  const key = symbol.toUpperCase();
  const existing = tickerInflight.get(key);
  if (existing) return existing;
  const p = api
    .tickerDetail(key)
    .then((d) => {
      tickerCache.set(key, d);
      return d;
    })
    .finally(() => {
      tickerInflight.delete(key);
    });
  tickerInflight.set(key, p);
  return p;
}

function fetchPriceHistory(symbol: string): Promise<PriceHistoryResponse> {
  const key = symbol.toUpperCase();
  const existing = priceInflight.get(key);
  if (existing) return existing;
  const p = api
    .priceHistory(key)
    .then((d) => {
      priceCache.set(key, d);
      return d;
    })
    .finally(() => {
      priceInflight.delete(key);
    });
  priceInflight.set(key, p);
  return p;
}

function fetchIndustry(slug: string): Promise<IndustryDetailResponse> {
  // Industry slugs aren't uppercased the way tickers are — keep them
  // verbatim so the cache key matches the URL the user actually visits.
  const existing = industryInflight.get(slug);
  if (existing) return existing;
  const p = api
    .industryDetail(slug)
    .then((d) => {
      industryCache.set(slug, d);
      return d;
    })
    .finally(() => {
      industryInflight.delete(slug);
    });
  industryInflight.set(slug, p);
  return p;
}

/**
 * Warm the ticker-detail + price-history caches without rendering them.
 * Safe to call repeatedly — cached results short-circuit and in-flight
 * requests are deduped. Failures are swallowed: prefetch is best-effort,
 * and the on-screen hook will surface any real error on the actual tap.
 */
export function prefetchTickerDetail(symbol: string): void {
  const key = symbol.toUpperCase();
  if (!tickerCache.has(key) && !tickerInflight.has(key)) {
    fetchTicker(key).catch(() => undefined);
  }
  if (!priceCache.has(key) && !priceInflight.has(key)) {
    fetchPriceHistory(key).catch(() => undefined);
  }
}

/**
 * SWR-style hook: returns cached data synchronously if present (so the UI
 * never sees a spinner on a revisit), then revalidates in the background.
 * `loading` is only true on the very first fetch for a given key.
 *
 * `normalize` defaults to uppercasing (correct for ticker symbols). Pass
 * the identity function for keys that are already canonical (e.g. URL
 * slugs).
 */
function useCachedFetch<T>(
  cache: Map<string, T>,
  fetcher: (key: string) => Promise<T>,
  rawKey: string | undefined,
  normalize: (k: string) => string = (k) => k.toUpperCase(),
): Async<T> {
  const key = rawKey ? normalize(rawKey) : undefined;
  const cached = key ? cache.get(key) ?? null : null;
  const [data, setData] = useState<T | null>(cached);
  const [loading, setLoading] = useState<boolean>(!cached && !!key);
  const [error, setError] = useState<string | null>(null);
  // Track the key the current state belongs to so a key change resets
  // the view before the new fetch completes (no flash of stale data).
  const currentKey = useRef<string | undefined>(key);

  const refresh = useCallback(async () => {
    if (!key) return;
    setError(null);
    try {
      const fresh = await fetcher(key);
      // Drop the result if the user has already navigated to a different
      // ticker in the meantime.
      if (currentKey.current === key) setData(fresh);
    } catch (e) {
      if (currentKey.current === key) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    } finally {
      if (currentKey.current === key) setLoading(false);
    }
  }, [key, fetcher]);

  useEffect(() => {
    currentKey.current = key;
    if (!key) {
      setData(null);
      setLoading(false);
      return;
    }
    const c = cache.get(key) ?? null;
    setData(c);
    setLoading(!c);
    setError(null);
    refresh();
  }, [key, cache, refresh]);

  return { data, loading, error, refresh };
}

export function usePriceHistory(symbol: string | undefined): Async<PriceHistoryResponse> {
  return useCachedFetch(priceCache, fetchPriceHistory, symbol);
}

export function useTickerDetail(symbol: string | undefined): Async<TickerDetail> {
  return useCachedFetch(tickerCache, fetchTicker, symbol);
}

export function useLatestDigest(): Async<DigestResponse> {
  return useAsync(() => api.latestDigest(), []);
}

export function useRecentDigests(limit: number = 10): Async<RecentDigestsResponse> {
  return useAsync(() => api.recentDigests(limit), [limit]);
}

export function useIndustryDetail(slug: string | undefined): Async<IndustryDetailResponse> {
  // Slugs are already canonical (lowercase + hyphens) — skip the default
  // uppercase normalization so the cache key matches the URL verbatim.
  return useCachedFetch(industryCache, fetchIndustry, slug, (s) => s);
}

// ---------------------------------------------------------------------------
// Industries list — shared by the home screen AND the iPad-landscape
// sidebar, which both render simultaneously. Cache it module-level so the
// two renderers don't fire duplicate `/api/industries` requests.
// ---------------------------------------------------------------------------
let industriesCache: IndustryListResponse | null = null;
let industriesInflight: Promise<IndustryListResponse> | null = null;

function fetchIndustries(): Promise<IndustryListResponse> {
  if (industriesInflight) return industriesInflight;
  industriesInflight = api
    .listIndustries()
    .then((d) => {
      industriesCache = d;
      return d;
    })
    .finally(() => {
      industriesInflight = null;
    });
  return industriesInflight;
}

export function useIndustries(): Async<IndustryListResponse> {
  const [data, setData] = useState<IndustryListResponse | null>(industriesCache);
  const [loading, setLoading] = useState<boolean>(!industriesCache);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      // Bust the cache on a manual refresh so pull-to-refresh actually
      // hits the network instead of replaying the cached payload.
      industriesCache = null;
      const fresh = await fetchIndustries();
      setData(fresh);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (industriesCache) {
      setData(industriesCache);
      setLoading(false);
      return;
    }
    fetchIndustries()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  return { data, loading, error, refresh };
}
