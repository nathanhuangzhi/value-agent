/**
 * Sync the Saved tab to the pipeline box (`/watchlist`, next to `/ai` on
 * the same host). Fire-and-forget: the phone's AsyncStorage stays the
 * source of truth for what the user sees; the server copy is what the
 * daily run reads to fetch data for saved companies.
 */
import { APP_TOKEN_HEADER, ApiError, BASE_URL } from './client';
import { authHeaders } from './session';

const WATCHLIST_URL = (
  process.env.EXPO_PUBLIC_WATCHLIST_URL?.replace(/\/$/, '') ??
  BASE_URL.replace(/\/reports$/, '/watchlist')
);

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${WATCHLIST_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      cache: 'no-store',
      ...init,
      headers: { 'content-type': 'application/json', ...APP_TOKEN_HEADER, ...authHeaders(), ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(0, `Network error reaching ${url}: ${e}`);
  }
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText} at ${url}`);
  return (await res.json()) as T;
}

export type WatchlistResponse = { tickers: string[]; unknown: string[] };

export const watchlistApi = {
  get: () => req<WatchlistResponse>(''),
  /** Union-adds; never removes. */
  add: (tickers: string[]) => req<WatchlistResponse>('', { method: 'PUT', body: JSON.stringify({ tickers }) }),
  remove: (ticker: string) => req<WatchlistResponse>(`/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
};
