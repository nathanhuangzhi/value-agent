/**
 * Display formatters. Mirror the Python `_format_money_compact` /
 * `_fmt_pct` / `_fmt_num` helpers in `app/tools/report/format.py` so
 * the mobile UI shows the same numbers users see in the web reports.
 */

export function formatMoney(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${Math.round(n / 1e6).toLocaleString()}M`;
  if (abs >= 1e3) return `$${Math.round(n / 1e3).toLocaleString()}K`;
  return `$${Math.round(n).toLocaleString()}`;
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
export function formatStockPrice(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  if (n >= 100) return `$${Math.round(n).toLocaleString()}`;
  if (n >= 10) return `$${n.toFixed(1)}`;
  return `$${n.toFixed(2)}`;
}
