/**
 * Monthly time series of Static P/E, Static P/S, and P/B — mirrors the
 * Python `_compute_valuation_history_monthly` helper in
 * `app/tools/report/ratios.py`. Used by the ticker-screen valuation grid
 * to plot each multiple over time alongside the stock price.
 *
 * Approach (per price point):
 *   1. Look up the latest annual NI / Revenue with period_end ≤ month
 *      → these are the "static" denominators that hold across quarters
 *   2. Look up the latest diluted-share count (quarterly preferred, annual fallback)
 *   3. mcap = price × shares
 *   4. Static P/E = mcap / annual_ni; Static P/S = mcap / annual_rev;
 *      P/B = mcap / book_value (book value: quarterly preferred over annual)
 *
 * Points with NO computable ratio are dropped — keeps the chart from
 * showing flat-zero stretches at the start of the price history before
 * any quarterly filing existed.
 */
import type { Period, PricePoint, Statements } from '@/api/types';


export type ValuationPoint = {
  date: string;
  price: number;
  static_pe: number | null;
  static_ps: number | null;
  pb: number | null;
};


function pickFirst(items: Record<string, number | null>, keys: string[]): number | null {
  for (const k of keys) {
    const v = items[k];
    if (v != null && isFinite(v)) return v;
  }
  return null;
}


function latestValueAtOrBefore(
  sortedAsc: Period[],
  monthYYYYMM: string,
  keys: string[],
): number | null {
  let best: number | null = null;
  for (const p of sortedAsc) {
    const periodMonth = (p.period || '').slice(0, 7);
    if (periodMonth > monthYYYYMM) break;
    const v = pickFirst(p.items as Record<string, number | null>, keys);
    if (v != null) best = v;
  }
  return best;
}


const NI_KEYS = ['Net Income', 'Net Income Common Stockholders'];
const REVENUE_KEYS = ['Total Revenue', 'Operating Revenue'];
const SHARES_KEYS = ['Diluted Average Shares', 'Basic Average Shares'];
const BV_KEYS = ['Common Stock Equity', 'Stockholders Equity', 'Total Equity Gross Minority Interest'];


export function computeValuationHistory(
  annual: Statements,
  quarterly: Statements,
  priceHistory: PricePoint[] | undefined | null,
): ValuationPoint[] {
  if (!priceHistory || priceHistory.length === 0) return [];

  const incQSorted = [...(quarterly.income_statement || [])].sort((a, b) => a.period.localeCompare(b.period));
  const bsQSorted = [...(quarterly.balance_sheet || [])].sort((a, b) => a.period.localeCompare(b.period));
  const incASorted = [...(annual.income_statement || [])].sort((a, b) => a.period.localeCompare(b.period));
  const bsASorted = [...(annual.balance_sheet || [])].sort((a, b) => a.period.localeCompare(b.period));

  const sortedPrices = [...priceHistory]
    .filter((p) => p.date && p.close != null && isFinite(p.close))
    .sort((a, b) => a.date.localeCompare(b.date));

  const out: ValuationPoint[] = [];
  for (const pt of sortedPrices) {
    const month = pt.date.slice(0, 7);

    const annualNi = latestValueAtOrBefore(incASorted, month, NI_KEYS);
    const annualRev = latestValueAtOrBefore(incASorted, month, REVENUE_KEYS);

    const shares =
      latestValueAtOrBefore(incQSorted, month, SHARES_KEYS) ??
      latestValueAtOrBefore(incASorted, month, SHARES_KEYS);
    if (shares == null) continue;

    const mcap = shares * pt.close;

    const bv =
      latestValueAtOrBefore(bsQSorted, month, BV_KEYS) ??
      latestValueAtOrBefore(bsASorted, month, BV_KEYS);

    const staticPe = annualNi != null && annualNi !== 0 ? mcap / annualNi : null;
    const staticPs = annualRev != null && annualRev !== 0 ? mcap / annualRev : null;
    const pb = bv != null && bv !== 0 ? mcap / bv : null;

    if (staticPe == null && staticPs == null && pb == null) continue;

    out.push({ date: pt.date, price: pt.close, static_pe: staticPe, static_ps: staticPs, pb });
  }
  return out;
}
