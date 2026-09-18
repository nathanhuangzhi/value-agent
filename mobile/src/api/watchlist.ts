/**
 * The account's named lists on the box (`/watchlist/lists`, next to `/ai`).
 * The phone keeps a cached copy (useSaved) so the tab renders offline;
 * the server copy is what the daily run reads to fetch data for saved
 * companies.
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
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep the status text */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export type Watchlist = { id: number; name: string; position: number; tickers: string[] };

export const watchlistApi = {
  lists: () => req<{ lists: Watchlist[] }>('/lists').then((r) => r.lists),
  create: (name: string) => req<Watchlist>('/lists', { method: 'POST', body: JSON.stringify({ name }) }),
  rename: (id: number, name: string) => req<Watchlist>(`/lists/${id}`, { method: 'PUT', body: JSON.stringify({ name }) }),
  reorder: (id: number, position: number) => req<Watchlist>(`/lists/${id}`, { method: 'PUT', body: JSON.stringify({ position }) }),
  remove: (id: number) => req<{ deleted: number }>(`/lists/${id}`, { method: 'DELETE' }),
  add: (id: number, tickers: string[]) => req<Watchlist>(`/lists/${id}/tickers`, { method: 'PUT', body: JSON.stringify({ tickers }) }),
  removeTicker: (id: number, ticker: string) => req<Watchlist>(`/lists/${id}/tickers/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
};
