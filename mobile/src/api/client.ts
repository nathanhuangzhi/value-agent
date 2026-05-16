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

export const api = {
  listIndustries: () => get<IndustryListResponse>('/industries'),
  industryDetail: (slug: string) =>
    get<IndustryDetailResponse>(`/industries/${encodeURIComponent(slug)}`),
  tickerDetail: (symbol: string) =>
    get<TickerDetail>(`/tickers/${encodeURIComponent(symbol.toUpperCase())}`),
  priceHistory: (symbol: string) =>
    get<PriceHistoryResponse>(`/tickers/${encodeURIComponent(symbol.toUpperCase())}/price-history`),
  latestDigest: () => get<DigestResponse>('/digest/latest'),
};

export { ApiError, BASE_URL };
