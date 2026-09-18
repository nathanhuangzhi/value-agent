/**
 * The historical-statements table's data model: which columns and rows
 * exist, which asset / liability lines to surface, per-cell formatting
 * and the YoY tint thresholds. Pure functions — no React — so the ticker
 * page (sticky header) and tests can use them without rendering.
 */
import type { Period, Statements } from '@/api/types';

export const MAX_ANNUAL = 10;
export const MAX_QUARTERLY = 8;
export const LABEL_WIDTH = 132;
export const CELL_WIDTH = 70;
export const ROW_HEIGHT = 30;
export const HEADER_HEIGHT = 28;
export const SECTION_HEADER_HEIGHT = 26;


// YoY thresholds — match `_yoy_cell_style` in Python
export const YOY_GREEN = 0.20;
export const YOY_RED = -0.20;


export type StatementSource = 'income' | 'balance' | 'cash_flow';

export type Column = {
  kind: 'annual' | 'quarterly';
  period: string;             // ISO date like "2025-12-28"
  label: string;              // "FY25" or "Q1'26"
};

export type RawRow = {
  kind: 'raw';
  label: string;
  source: StatementSource;
  keys: string[];             // candidate item keys in priority order
  /** money: adaptive units — picks K/M/B/T per value so a micro-cap keeps
   * precision ("-77K") while a large cap stays compact ("11M"). Mirrors the
   * digest's formatMoney so the same figure reads identically on both
   * screens (the whole point of this format — see the ACFN bug).
   * shares: raw share count with adaptive K/M/B units ("1.4M", "850K").
   * per_share: typical EPS/BVPS scale → "$1.23" or "$123". */
  format: 'money' | 'shares' | 'per_share';
  abs?: boolean;
  /** Draw a rule above this row (e.g. to split liabilities from assets). */
  dividerAbove?: boolean;
};

/**
 * Generic ratio row. Three families share this shape:
 *   - Profitability margins (Gross / Operating / Net): GP|OI|NI / Revenue
 *   - Opex ratios (R&D / SG&A / S&M / G&A / Other Opex): expense / Revenue
 *   - Per-share metrics (Sales Per Share, Book Value Per Share)
 *
 * Numerator may be a literal lookup or the computed "Other Opex"
 * (Gross Profit − Operating Income − R&D − SG&A). Denominator may be a
 * literal lookup or the diluted-share count (with quarterly fallback).
 * The two compute keywords are deliberately on different sides — the
 * types enforce that an "other_opex denominator" isn't expressible.
 */
export type RatioNumerator =
  | { source: StatementSource; keys: string[] }
  | { compute: 'other_opex' };

export type RatioDenominator =
  | { source: StatementSource; keys: string[] }
  | { compute: 'shares' };

export type RatioRow = {
  kind: 'ratio';
  label: string;
  numerator: RatioNumerator;
  denominator: RatioDenominator;
  /** percent → "12%" / "8.5%"; per_share → "$1.23" / "$15". */
  format: 'percent' | 'per_share';
};

export type ValuationRow = {
  kind: 'valuation';
  label: string;
  /** mcap_now / annual-baseline. The richer TTM / EV / yield variants
   * live in the 2×2 chart grid (`ValuationGrid`); the table sticks to
   * three "static" multiples grounded at each period. */
  metric:
    | 'static_pe'   // mcap_now / most-recent annual NI ≤ this period
    | 'static_ps'   // mcap_now / most-recent annual Revenue ≤ this period
    | 'pb';         // mcap_now / book value at this period
};

/** A user's metric or extracted series: server-evaluated per period. */
export type CustomRow = {
  kind: 'custom';
  label: string;
  format: 'number' | 'ratio' | 'pct' | 'money' | 'bool';
  annual: Record<string, number | null>;
  quarterly: Record<string, number | null>;
};

export type Row = RawRow | RatioRow | ValuationRow | CustomRow;

export type Section = {
  title: string;
  rows: Row[];
};


// ====== Top-asset detection (port of ratios._top_asset_keys) ======

export const ASSET_CANDIDATE_KEYS = [
  'Goodwill',
  'Other Intangible Assets',
  'Goodwill And Other Intangible Assets',
  'Net PPE',
  'Property Plant And Equipment Net',
  'Property Plant And Equipment Gross',
  'Gross PPE',
  'Inventory',
  'Receivables',
  'Accounts Receivable',
  'Other Short Term Investments',
  'Available For Sale Securities',
  'Long Term Investments',
  'Other Investments',
  'Investments And Advances',
  'Other Non Current Assets',
  'Other Assets',
];

export const ASSET_KEY_CATEGORY: Record<string, string> = {
  'Goodwill': 'goodwill',
  'Other Intangible Assets': 'intangibles',
  'Goodwill And Other Intangible Assets': 'intangibles',
  'Net PPE': 'ppe',
  'Property Plant And Equipment Net': 'ppe',
  'Property Plant And Equipment Gross': 'ppe',
  'Gross PPE': 'ppe',
  'Inventory': 'inventory',
  'Receivables': 'receivables',
  'Accounts Receivable': 'receivables',
  'Other Short Term Investments': 'investments',
  'Available For Sale Securities': 'investments',
  'Long Term Investments': 'investments',
  'Other Investments': 'investments',
  'Investments And Advances': 'investments',
  'Other Non Current Assets': 'other_assets',
  'Other Assets': 'other_assets',
};

export function topAssetKeys(annualBS: Period[], quarterlyBS: Period[], topN?: number): string[] {
  // Quarterly preferred over annual since it's more recent. Within each,
  // newest first.
  const newestQ = [...quarterlyBS].sort((a, b) => b.period.localeCompare(a.period));
  const newestA = [...annualBS].sort((a, b) => b.period.localeCompare(a.period));

  let latestItems: Record<string, number | null> | null = null;
  for (const p of [...newestQ, ...newestA]) {
    const items = p.items as Record<string, number | null>;
    if (ASSET_CANDIDATE_KEYS.some((k) => items[k] != null && (items[k] as number) > 0)) {
      latestItems = items;
      break;
    }
  }
  if (!latestItems) return [];

  const seenCategories = new Set<string>();
  const scored: { key: string; value: number }[] = [];
  for (const key of ASSET_CANDIDATE_KEYS) {
    const v = latestItems[key];
    if (v == null || v <= 0) continue;
    const category = ASSET_KEY_CATEGORY[key] || key;
    if (seenCategories.has(category)) continue;
    scored.push({ key, value: v });
    seenCategories.add(category);
  }
  scored.sort((a, b) => b.value - a.value);
  return (topN ? scored.slice(0, topN) : scored).map((x) => x.key);
}

// ====== Top-liability detection (port of ratios._top_liability_keys) ======

export const LIABILITY_CANDIDATE_KEYS = [
  'Long Term Debt',
  'Current Debt',
  'Accounts Payable',
  'Accrued Liabilities',
  'Deferred Revenue',
  'Lease Obligations',
];

export function topLiabilityKeys(annualBS: Period[], quarterlyBS: Period[], topN: number = 3): string[] {
  const newestQ = [...quarterlyBS].sort((a, b) => b.period.localeCompare(a.period));
  const newestA = [...annualBS].sort((a, b) => b.period.localeCompare(a.period));
  for (const p of [...newestQ, ...newestA]) {
    const items = p.items as Record<string, number | null>;
    const scored = LIABILITY_CANDIDATE_KEYS
      .filter((k) => items[k] != null && (items[k] as number) > 0)
      .map((k) => ({ key: k, value: items[k] as number }));
    if (scored.length) {
      scored.sort((a, b) => b.value - a.value);
      return scored.slice(0, topN).map((x) => x.key);
    }
  }
  return [];
}


// ====== Label / formatting helpers ======

export function fyLabel(period: string): string {
  const m = period.match(/^(\d{4})-(\d{2})/);
  if (!m) return 'FY' + period.slice(2, 4);
  const y = parseInt(m[1]);
  const mo = parseInt(m[2]);
  const fy = mo >= 6 ? y : y - 1;
  return `FY${String(fy).slice(-2)}`;
}

export function quarterLabel(period: string): string {
  const m = period.match(/^(\d{4})-(\d{2})/);
  if (!m) return period.slice(0, 7);
  const y = parseInt(m[1]);
  const mo = parseInt(m[2]);
  const q = Math.floor((mo - 1) / 3) + 1;
  return `Q${q}'${String(y).slice(-2)}`;
}

export function pickFirst(items: Record<string, number | null>, keys: string[]): number | null {
  for (const k of keys) {
    const v = items[k];
    if (v != null && isFinite(v)) return v;
  }
  return null;
}

export function pickSource(sources: Record<string, string> | undefined, keys: string[]): string | undefined {
  if (!sources) return undefined;
  for (const k of keys) if (sources[k]) return sources[k];
  return undefined;
}

/**
 * Compact $-value for a table cell with adaptive units. Picks the largest
 * unit that keeps the number readable (K/M/B/T) and shows one decimal only
 * when the scaled magnitude is < 10 — mirroring the web report's `_fmt` and
 * the digest's `formatMoney`. No "$" prefix: the cell stays narrow and the
 * unit suffix carries the scale. Examples: -77000 → "-77K", 2_227_000 →
 * "2.2M", 11_478_000 → "11M". Sub-$1,000 values render raw ("500").
 */
export function formatMoneyCell(value: number): string {
  const abs = Math.abs(value);
  let scaled = value;
  let suffix = '';
  if (abs >= 1e12) { scaled = value / 1e12; suffix = 'T'; }
  else if (abs >= 1e9) { scaled = value / 1e9; suffix = 'B'; }
  else if (abs >= 1e6) { scaled = value / 1e6; suffix = 'M'; }
  else if (abs >= 1e3) { scaled = value / 1e3; suffix = 'K'; }
  const decs = suffix && Math.abs(scaled) < 10 ? 1 : 0;
  return scaled.toLocaleString(undefined, {
    minimumFractionDigits: decs,
    maximumFractionDigits: decs,
  }) + suffix;
}

export function formatCell(value: number | null, row: RawRow, fx: number = 1): string {
  if (value == null) return '—';
  const scaled = row.format === 'shares' ? value : value * fx;
  const v = row.abs ? Math.abs(scaled) : scaled;
  if (row.format === 'per_share') {
    return Math.abs(v) < 10 ? v.toFixed(1) : Math.round(v).toLocaleString();
  }
  if (row.format === 'shares') {
    // Share counts get the same adaptive K/M/B units as money cells, so a
    // 1.4M-share micro-cap reads "1.4M" rather than a bare "1".
    return formatMoneyCell(v);
  }
  return formatMoneyCell(v);
}

export function formatMargin(num: number | null, den: number | null): string {
  if (num == null || den == null || den === 0) return '—';
  const pct = (num / den) * 100;
  return Math.abs(pct) < 10 ? pct.toFixed(1) + '%' : Math.round(pct) + '%';
}

export function formatPerShare(num: number | null, den: number | null, fx: number = 1): string {
  if (num == null || den == null || den === 0) return '—';
  const v = (num / den) * fx;
  // Per-share values are in raw dollars (revenue / equity in $ ÷ share count).
  // <$10 gets 2 decimals (typical EPS / BVPS scale); ≥$10 rounds to integer.
  return Math.abs(v) < 10 ? `$${v.toFixed(2)}` : `$${Math.round(v).toLocaleString()}`;
}

export function formatRatio(v: number | null): string {
  if (v == null || !isFinite(v)) return '—';
  return Math.abs(v) < 10 ? `${v.toFixed(1)}x` : `${Math.round(v).toLocaleString()}x`;
}


// Shared candidate-key lists referenced by multiple ratio rows.
export const REVENUE_KEYS = ['Total Revenue', 'Operating Revenue'];
export const NI_KEYS = ['Net Income', 'Net Income Common Stockholders'];
export const SHARES_KEYS = ['Diluted Average Shares', 'Basic Average Shares'];

export function yoyDelta(curr: number | null, prev: number | null): number | null {
  if (curr == null || prev == null || prev === 0) return null;
  return (curr - prev) / Math.abs(prev);
}

/** Walks a sorted-ascending period list and returns the latest value at
 * or before `cutoff`. Used to lock the "static" annual baseline. */
export function latestAtOrBefore(periods: Period[], cutoff: string, keys: string[]): number | null {
  let best: number | null = null;
  for (const p of periods) {
    if (p.period > cutoff) break;
    const v = pickFirst(p.items as Record<string, number | null>, keys);
    if (v != null) best = v;
  }
  return best;
}

// ====== Component ======


export function byPeriod(periods: Period[]): Map<string, Period> {
  return new Map(periods.map((p) => [p.period, p]));
}


/**
 * Compute the columns the table renders, plus the divider index between
 * annual and quarterly periods. Exposed so the ticker page can render a
 * stand-alone sticky period-header overlay that mirrors the table.
 */
export function computeHistoricalTableColumns(
  statements: Statements,
  quarterly: Statements,
): { columns: Column[]; dividerIdx: number } {
  const annualPeriods = statements.income_statement.slice(-MAX_ANNUAL);
  const quarterlyPeriods = quarterly.income_statement.slice(-MAX_QUARTERLY);
  return {
    columns: [
      ...annualPeriods.map<Column>((p) => ({
        kind: 'annual',
        period: p.period,
        label: fyLabel(p.period),
      })),
      ...quarterlyPeriods.map<Column>((p) => ({
        kind: 'quarterly',
        period: p.period,
        label: quarterLabel(p.period),
      })),
    ],
    dividerIdx: annualPeriods.length,
  };
}
