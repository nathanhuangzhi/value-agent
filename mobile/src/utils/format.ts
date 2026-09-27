/**
 * Display formatters. Mirror the Python `_format_money_compact` /
 * `_fmt_pct` / `_fmt_num` helpers in `app/tools/report/format.py` so
 * the mobile UI shows the same numbers users see in the web reports.
 */

/** `currency` is a code like 'USD' or 'CNY'; list views leave it at the
 * default so a mixed table stays comparable in dollars. */
const CURRENCY_SYMBOL: Record<string, string> = { USD: '$', CNY: '¥', HKD: 'HK$', EUR: '€', GBP: '£', JPY: '¥' };

export function currencySymbol(currency: string | null | undefined): string {
  return CURRENCY_SYMBOL[(currency || 'USD').toUpperCase()] ?? '';
}

export function formatMoney(n: number | null | undefined, currency: string = 'USD'): string {
  if (n == null || !isFinite(n)) return '—';
  const s = currencySymbol(currency);
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${s}${(n / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${s}${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${s}${Math.round(n / 1e6).toLocaleString()}M`;
  if (abs >= 1e3) return `${s}${Math.round(n / 1e3).toLocaleString()}K`;
  return `${s}${Math.round(n).toLocaleString()}`;
}

export function formatRatio(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  // 1 decimal when |n| < 10 so 8.3x stays useful; integer when bigger so
  // 12x doesn't waste pixels.
  return Math.abs(n) < 10 ? `${n.toFixed(1)}x` : `${n.toFixed(0)}x`;
}

export function formatPct(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  const v = n * 100;
  return Math.abs(v) < 10 ? `${v.toFixed(1)}%` : `${v.toFixed(0)}%`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  // Truncate ISO datetime to date if needed (e.g. 2026-05-09T18:00:00Z → 2026-05-09)
  return iso.slice(0, 10);
}

/**
 * Format a raw stock price for a chart tooltip / KPI label. Unlike
 * `formatMoney`, which abbreviates large dollar amounts to "$1.2B",
 * this keeps the full dollar value with decimals scaled to magnitude:
 *   >= $100  → no decimals ($1,234)
 *   >= $10   → one decimal  ($87.4)
 *   <  $10   → two decimals ($5.23)
 */
/** A quoted share price. `currency` is the payload's `quote_currency` — an
 * A-share trades in CNY, so labelling it `$` would misstate it. */
export function formatStockPrice(n: number | null | undefined, currency: string = 'USD'): string {
  if (n == null || !isFinite(n)) return '—';
  const sym = currencySymbol(currency);
  if (n >= 100) return `${sym}${Math.round(n).toLocaleString()}`;
  if (n >= 10) return `${sym}${n.toFixed(1)}`;
  return `${sym}${n.toFixed(2)}`;
}

/** Industry name → URL slug. Mirrors `_slug` in app/api/routes.py. */
export function slugify(s: string | null | undefined): string {
  if (!s) return 'uncategorized';
  const out = s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return out || 'uncategorized';
}

/** Short label for a chat model id ("deepseek-v4-pro" → "Pro", "claude-…" → "Claude"). */
export function modelLabel(id: string | null | undefined): string {
  if (!id) return '';
  if (id.startsWith('claude')) return 'Claude';
  return id.includes('pro') ? 'Pro' : 'Flash';
}
