/**
 * Thin fetch wrapper around the FastAPI `/api/...` endpoints.
 *
 * Base URL comes from `EXPO_PUBLIC_API_URL` in `.env` — Expo injects
 * any env var prefixed with `EXPO_PUBLIC_` into the bundle at build
 * time. For physical-device dev, this must be your laptop's LAN IP
 * (not `localhost`).
 */
import type {
  DigestResponse,
  IndustryDetailResponse,
  IndustryListResponse,
  PriceHistoryResponse,
  RecentDigestsResponse,
  TickerDetail,
} from './types';

const BASE_URL =
  process.env.EXPO_PUBLIC_API_URL?.replace(/\/$/, '') ??
  'http://localhost:8000';

class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function get<T>(path: string): Promise<T> {
  const url = `${BASE_URL}/api${path}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new ApiError(0, `Network error reaching ${url}: ${e}`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText} at ${url}`);
  }
  return (await res.json()) as T;
}

// Every endpoint now resolves to a static `.json` file. In prod the files
// live on a CDN (Vercel), baked once a day by `scripts/bake_api.py`. In
// local dev the same FastAPI routes serve them with the same paths, so
// the client code is identical against either backend.
export const api = {
  listIndustries: () => get<IndustryListResponse>('/industries.json'),
  industryDetail: (slug: string) =>
    get<IndustryDetailResponse>(`/industries/${encodeURIComponent(slug)}.json`),
  tickerDetail: (symbol: string) =>
    get<TickerDetail>(`/tickers/${encodeURIComponent(symbol.toUpperCase())}.json`),
  priceHistory: (symbol: string) =>
    get<PriceHistoryResponse>(`/tickers/${encodeURIComponent(symbol.toUpperCase())}/price-history.json`),
  latestDigest: () => get<DigestResponse>('/digest/latest.json'),
  // The baked `recent.json` always contains `RECENT_DIGESTS_LIMIT` (20)
  // entries — the `limit` arg slices client-side so a future bake-size
  // change doesn't break call sites.
  recentDigests: (limit: number = 10) =>
    get<RecentDigestsResponse>('/digests/recent.json').then((r) => ({
      digests: (r.digests ?? []).slice(0, limit),
    })),
};

export { ApiError, BASE_URL };
