/**
 * Reusable data hooks built on top of the `api` client. Each hook returns
 * `{ data, loading, error, refresh }` — a small surface that's the same
 * across endpoints, so screens look identical regardless of which one
 * they're fetching from.
 *
 * The hooks deliberately don't use react-query / SWR yet — the app is
 * small enough that the extra dependency isn't justified. Migrate later
 * if you add caching across screens or background refresh.
 */
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from './client';
import type { DigestResponse, PriceHistoryResponse, TickerDetail } from './types';

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

export function usePriceHistory(symbol: string | undefined): Async<PriceHistoryResponse> {
  return useAsync(
    () => {
      if (!symbol) throw new ApiError(0, 'no symbol');
      return api.priceHistory(symbol);
    },
    [symbol],
  );
}

export function useTickerDetail(symbol: string | undefined): Async<TickerDetail> {
  return useAsync(
    () => {
      if (!symbol) throw new ApiError(0, 'no symbol');
      return api.tickerDetail(symbol);
    },
    [symbol],
  );
}

export function useLatestDigest(): Async<DigestResponse> {
  return useAsync(() => api.latestDigest(), []);
}
