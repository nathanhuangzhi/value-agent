/** Custom metrics (per account) — /me/metrics on the box. */
import { APP_TOKEN_HEADER, ApiError, BASE_URL } from './client';
import { authHeaders } from './session';

const ROOT = BASE_URL.replace(/\/reports$/, '');

export type MetricFormat = 'number' | 'ratio' | 'pct' | 'money' | 'bool';
export type Metric = { id: number; name: string; expr: string; format: MetricFormat; position: number; created_at: string; updated_at: string; applies_to?: string[] | null };
export type SeriesPoint = { period: string; value: number | null };
export type Evaluated = Metric & { series: SeriesPoint[]; latest: number | null; error: string | null };
export type PreviewResult = { series: SeriesPoint[]; latest: number | null; format: MetricFormat } | { error: string };
export type ChartSeriesData = { label: string; kind: 'line' | 'bar'; axis: 'left' | 'right'; format: MetricFormat; values: (number | null)[] };
export type ChartData = { id?: number; title: string; period?: 'quarterly' | 'annual'; periods?: string[]; series?: ChartSeriesData[]; error?: string; position?: number };
export type ChartSpec = { title: string; period?: 'quarterly' | 'annual'; last_n?: number; series: { expr: string; label: string; kind?: 'line' | 'bar'; axis?: 'left' | 'right'; format?: MetricFormat }[] };
export type Chart = { id: number; title: string; spec: ChartSpec; position: number; created_at: string; updated_at: string; applies_to?: string[] | null };
export type CustomTableRow = { id: number | string; name: string; format: MetricFormat; annual: Record<string, number | null>; quarterly: Record<string, number | null> };
export type Series = { id: number; ticker: string; name: string; label: string; unit: 'number' | 'money' | 'pct' | 'ratio'; currency: string | null; grid: 'quarterly' | 'annual'; points: { period: string; value: number | null; source: string }[]; source_hint: string | null; last_source: string | null };
export type Aliases = {
  metrics: { alias: string; item: string; kind: string }[];
  derived: Record<string, string>;
  suffixes: string[];
  functions: Record<string, number>;
  formats: MetricFormat[];
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${ROOT}${path}`;
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
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep status text */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const metricsApi = {
  aliases: () => req<Aliases>('/me/metrics/aliases'),
  list: () => req<{ metrics: Metric[] }>('/me/metrics').then((r) => r.metrics),
  create: (body: { name: string; expr: string; format?: MetricFormat }) =>
    req<Metric>('/me/metrics', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: number, body: Partial<{ name: string; expr: string; format: MetricFormat; position: number }>) =>
    req<Metric>(`/me/metrics/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  remove: (id: number) => req<{ deleted: number }>(`/me/metrics/${id}`, { method: 'DELETE' }),
  preview: (expr: string, ticker: string) =>
    req<PreviewResult>('/me/metrics/preview', { method: 'POST', body: JSON.stringify({ expr, ticker }) }),
  forTicker: (ticker: string) => req<{ ticker: string; metrics: Evaluated[]; charts: ChartData[]; rows: CustomTableRow[] }>(`/me/tickers/${encodeURIComponent(ticker)}/custom.json`),
  charts: () => req<{ charts: Chart[] }>('/me/charts').then((r) => r.charts),
  series: () => req<{ series: Series[] }>('/me/series').then((r) => r.series),
  removeSeries: (id: number) => req<{ deleted: number }>(`/me/series/${id}`, { method: 'DELETE' }),
  removeChart: (id: number) => req<{ deleted: number }>(`/me/charts/${id}`, { method: 'DELETE' }),
  chartData: (id: number, ticker: string) => req<ChartData>(`/me/charts/${id}/data?ticker=${encodeURIComponent(ticker)}`),
};

/** Render a metric value in its declared format. */
export function formatMetric(v: number | null | undefined, format: MetricFormat): string {
  if (v == null || !isFinite(v)) return '—';
  switch (format) {
    case 'bool': return v ? '✓' : '✗';
    case 'pct': { const p = v * 100; return `${Math.abs(p) < 10 ? p.toFixed(1) : p.toFixed(0)}%`; }
    case 'ratio': return `${Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1)}x`;
    case 'money': {
      const a = Math.abs(v), sign = v < 0 ? '-' : '';
      if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(2)}T`;
      if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
      if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`;
      if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(0)}K`;
      return `${sign}$${a.toFixed(2)}`;
    }
    default: return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  }
}
