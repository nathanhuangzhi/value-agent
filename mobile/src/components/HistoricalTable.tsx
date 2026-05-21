/**
 * Historical financial statements as a frozen-left-column matrix with a
 * single horizontal scroll covering both annual and quarterly periods.
 *
 * Layout:
 *   [ METRIC col ][ FY16  FY17  …  FY25 │ Q2'24  Q3'24  …  Q1'26 ]
 *                                      ^
 *                                annual/quarterly divider
 *
 * Default scroll position is anchored to the rightmost column (the most
 * recent quarter), so the user lands on "what's happening now" and pans
 * left through older quarters and then annual history.
 *
 * Features ported from the web `tables.py`:
 *   - YoY color tinting (green ≥+20%, red ≤−20%) on raw $-value rows
 *   - Source provenance via italic text for yfinance-sourced cells
 *   - Computed margin rows (Gross / Operating / Net)
 *   - Per-period valuation multiples (Static P/E, Static P/S, P/B) —
 *     mcap = price × diluted shares; static baseline = most recent annual
 *     NI / Revenue ≤ this column
 *   - Top-2 non-cash asset rows in the Balance Sheet section — picks the
 *     largest categories (Goodwill / PPE / Inventory / Receivables / etc.)
 *     from the most recent balance sheet, deduped by category
 */
import { useCallback, useMemo, useRef } from 'react';
import { Animated, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import type { Period, PricePoint, Statements } from '@/api/types';
import { useColors, fontSize, spacing } from '@/theme/colors';


const MAX_ANNUAL = 10;
const MAX_QUARTERLY = 8;
const LABEL_WIDTH = 132;
const CELL_WIDTH = 70;
const ROW_HEIGHT = 30;
const HEADER_HEIGHT = 28;
const SECTION_HEADER_HEIGHT = 26;
// Fraction of the screen height the table is allowed to occupy. The inner
// body scrolls vertically so the period-header row stays pinned at top
// while the user scans down through metric rows. Capped so the table
// doesn't dominate huge iPad screens.
const TABLE_HEIGHT_RATIO = 0.65;
const TABLE_HEIGHT_MAX = 640;
const TABLE_HEIGHT_MIN = 360;

// YoY thresholds — match `_yoy_cell_style` in Python
const YOY_GREEN = 0.20;
const YOY_RED = -0.20;


type StatementSource = 'income' | 'balance' | 'cash_flow';

type Column = {
  kind: 'annual' | 'quarterly';
  period: string;             // ISO date like "2025-12-28"
  label: string;              // "FY25" or "Q1'26"
};

type RawRow = {
  kind: 'raw';
  label: string;
  source: StatementSource;
  keys: string[];             // candidate item keys in priority order
  /** millions: raw $ value divided by 1e6 → "1,234". Also used for raw
   * share counts since the math is identical (count ÷ 1e6 → "1,234").
   * per_share: typical EPS/BVPS scale → "$1.23" or "$123". */
  format: 'millions' | 'per_share';
  abs?: boolean;
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
type RatioNumerator =
  | { source: StatementSource; keys: string[] }
  | { compute: 'other_opex' };

type RatioDenominator =
  | { source: StatementSource; keys: string[] }
  | { compute: 'shares' };

type RatioRow = {
  kind: 'ratio';
  label: string;
  numerator: RatioNumerator;
  denominator: RatioDenominator;
  /** percent → "12%" / "8.5%"; per_share → "$1.23" / "$15". */
  format: 'percent' | 'per_share';
};

type ValuationRow = {
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

type Row = RawRow | RatioRow | ValuationRow;

type Section = {
  title: string;
  rows: Row[];
};


// ====== Top-asset detection (port of ratios._top_asset_keys) ======

const ASSET_CANDIDATE_KEYS = [
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

const ASSET_KEY_CATEGORY: Record<string, string> = {
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

function topAssetKeys(annualBS: Period[], quarterlyBS: Period[], topN: number = 2): string[] {
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
  return scored.slice(0, topN).map((x) => x.key);
}


// ====== Label / formatting helpers ======

function fyLabel(period: string): string {
  const m = period.match(/^(\d{4})-(\d{2})/);
  if (!m) return 'FY' + period.slice(2, 4);
  const y = parseInt(m[1]);
  const mo = parseInt(m[2]);
  const fy = mo >= 6 ? y : y - 1;
  return `FY${String(fy).slice(-2)}`;
}

function quarterLabel(period: string): string {
  const m = period.match(/^(\d{4})-(\d{2})/);
  if (!m) return period.slice(0, 7);
  const y = parseInt(m[1]);
  const mo = parseInt(m[2]);
  const q = Math.floor((mo - 1) / 3) + 1;
  return `Q${q}'${String(y).slice(-2)}`;
}

function pickFirst(items: Record<string, number | null>, keys: string[]): number | null {
  for (const k of keys) {
    const v = items[k];
    if (v != null && isFinite(v)) return v;
  }
  return null;
}

function pickSource(sources: Record<string, string> | undefined, keys: string[]): string | undefined {
  if (!sources) return undefined;
  for (const k of keys) if (sources[k]) return sources[k];
  return undefined;
}

function formatCell(value: number | null, row: RawRow): string {
  if (value == null) return '—';
  const v = row.abs ? Math.abs(value) : value;
  if (row.format === 'per_share') {
    return Math.abs(v) < 10 ? v.toFixed(1) : Math.round(v).toLocaleString();
  }
  return Math.round(v / 1e6).toLocaleString();
}

function formatMargin(num: number | null, den: number | null): string {
  if (num == null || den == null || den === 0) return '—';
  const pct = (num / den) * 100;
  return Math.abs(pct) < 10 ? pct.toFixed(1) + '%' : Math.round(pct) + '%';
}

function formatPerShare(num: number | null, den: number | null): string {
  if (num == null || den == null || den === 0) return '—';
  const v = num / den;
  // Per-share values are in raw dollars (revenue / equity in $ ÷ share count).
  // <$10 gets 2 decimals (typical EPS / BVPS scale); ≥$10 rounds to integer.
  return Math.abs(v) < 10 ? `$${v.toFixed(2)}` : `$${Math.round(v).toLocaleString()}`;
}

function formatRatio(v: number | null): string {
  if (v == null || !isFinite(v)) return '—';
  return Math.abs(v) < 10 ? `${v.toFixed(1)}x` : `${Math.round(v).toLocaleString()}x`;
}


// Shared candidate-key lists referenced by multiple ratio rows.
const REVENUE_KEYS = ['Total Revenue', 'Operating Revenue'];
const NI_KEYS = ['Net Income', 'Net Income Common Stockholders'];
const SHARES_KEYS = ['Diluted Average Shares', 'Basic Average Shares'];

function yoyDelta(curr: number | null, prev: number | null): number | null {
  if (curr == null || prev == null || prev === 0) return null;
  return (curr - prev) / Math.abs(prev);
}

/** Walks a sorted-ascending period list and returns the latest value at
 * or before `cutoff`. Used to lock the "static" annual baseline. */
function latestAtOrBefore(periods: Period[], cutoff: string, keys: string[]): number | null {
  let best: number | null = null;
  for (const p of periods) {
    if (p.period > cutoff) break;
    const v = pickFirst(p.items as Record<string, number | null>, keys);
    if (v != null) best = v;
  }
  return best;
}

// ====== Component ======

type Props = {
  statements: Statements;
  quarterly: Statements;
  priceHistory?: PricePoint[];
};


export function HistoricalTable({ statements, quarterly, priceHistory }: Props) {
  const c = useColors();
  const scrollRef = useRef<ScrollView>(null);
  const { height: screenH } = useWindowDimensions();
  // Drives both the data ScrollView's contentOffset.y and the matching
  // upward translation of the label column, keeping the two visually
  // synced as the user scrolls through metric rows.
  const scrollY = useRef(new Animated.Value(0)).current;

  const annualPeriods = statements.income_statement.slice(-MAX_ANNUAL);
  const quarterlyPeriods = quarterly.income_statement.slice(-MAX_QUARTERLY);

  const columns: Column[] = [
    ...annualPeriods.map<Column>((p) => ({ kind: 'annual', period: p.period, label: fyLabel(p.period) })),
    ...quarterlyPeriods.map<Column>((p) => ({ kind: 'quarterly', period: p.period, label: quarterLabel(p.period) })),
  ];

  // Pre-sorted annual income/balance for "latest-at-or-before" baselines.
  const sortedAnnualIncome = useMemo(
    () => [...statements.income_statement].sort((a, b) => a.period.localeCompare(b.period)),
    [statements.income_statement],
  );

  // Top 2 non-cash asset categories (e.g., ['Goodwill', 'Net PPE']),
  // determined once per ticker from the most recent balance sheet.
  const assetKeys = useMemo(
    () => topAssetKeys(statements.balance_sheet, quarterly.balance_sheet),
    [statements.balance_sheet, quarterly.balance_sheet],
  );

  // Does this ticker report S&M and G&A separately (≥2 periods each)? If
  // so, the opex section breaks them out; otherwise it collapses to
  // combined SG&A. Mirrors the `opex_breakout` heuristic in Python.
  const opexBreakout = useMemo(() => {
    let smCount = 0;
    let gaCount = 0;
    for (const arr of [statements.income_statement, quarterly.income_statement]) {
      for (const p of arr) {
        const items = (p.items || {}) as Record<string, number | null>;
        if (pickFirst(items, ['Selling And Marketing Expense']) != null) smCount++;
        if (pickFirst(items, ['General And Administrative Expense']) != null) gaCount++;
      }
    }
    return smCount >= 2 && gaCount >= 2;
  }, [statements.income_statement, quarterly.income_statement]);

  // Price lookup keyed by YYYY-MM. The chart already gets a sorted
  // ascending price_history; build a Map keyed by month-string.
  const priceByMonth = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of priceHistory || []) {
      if (p.close != null) m.set(p.date.slice(0, 7), p.close);
    }
    return m;
  }, [priceHistory]);

  if (columns.length === 0) {
    return (
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>
        (no historical data available)
      </Text>
    );
  }

  // Lookup maps: kind + section → period → Period dict
  const lookup = {
    annual: {
      income: byPeriod(statements.income_statement),
      balance: byPeriod(statements.balance_sheet),
      cash_flow: byPeriod(statements.cash_flow),
    },
    quarterly: {
      income: byPeriod(quarterly.income_statement),
      balance: byPeriod(quarterly.balance_sheet),
      cash_flow: byPeriod(quarterly.cash_flow),
    },
  };

  const dividerIdx = annualPeriods.length;

  // Build sections dynamically because Balance Sheet's top-asset rows
  // depend on the ticker's actual data, and Valuation Multiples is only
  // included when we have a price history to ground the math.
  const sections: Section[] = [
    {
      title: 'Income Statement ($M)',
      rows: [
        { kind: 'raw', label: 'Revenue',          source: 'income', keys: ['Total Revenue', 'Operating Revenue'], format: 'millions' },
        { kind: 'raw', label: 'Gross Profit',     source: 'income', keys: ['Gross Profit'], format: 'millions' },
        { kind: 'raw', label: 'Operating Income', source: 'income', keys: ['Operating Income', 'Total Operating Income As Reported'], format: 'millions' },
        { kind: 'raw', label: 'Net Income',       source: 'income', keys: ['Net Income', 'Net Income Common Stockholders'], format: 'millions' },
      ],
    },
    {
      title: 'Profitability Margins',
      rows: [
        { kind: 'ratio', label: 'Gross Margin',     format: 'percent',
          numerator:   { source: 'income', keys: ['Gross Profit'] },
          denominator: { source: 'income', keys: REVENUE_KEYS } },
        { kind: 'ratio', label: 'Operating Margin', format: 'percent',
          numerator:   { source: 'income', keys: ['Operating Income', 'Total Operating Income As Reported'] },
          denominator: { source: 'income', keys: REVENUE_KEYS } },
        { kind: 'ratio', label: 'Net Margin',       format: 'percent',
          numerator:   { source: 'income', keys: NI_KEYS },
          denominator: { source: 'income', keys: REVENUE_KEYS } },
      ],
    },
    {
      title: 'Operating Expense Ratios (% of revenue)',
      rows: [
        // Web logic: if both S&M and G&A are reported separately for at
        // least 2 periods anywhere in the data, show them split. Otherwise
        // fall back to the combined SG&A line.
        ...(opexBreakout
          ? [
              { kind: 'ratio', label: 'S&M / Revenue', format: 'percent',
                numerator:   { source: 'income', keys: ['Selling And Marketing Expense'] },
                denominator: { source: 'income', keys: REVENUE_KEYS } } as RatioRow,
              { kind: 'ratio', label: 'G&A / Revenue', format: 'percent',
                numerator:   { source: 'income', keys: ['General And Administrative Expense'] },
                denominator: { source: 'income', keys: REVENUE_KEYS } } as RatioRow,
            ]
          : [
              { kind: 'ratio', label: 'SG&A / Revenue', format: 'percent',
                numerator:   { source: 'income', keys: ['Selling General And Administration'] },
                denominator: { source: 'income', keys: REVENUE_KEYS } } as RatioRow,
            ]),
        { kind: 'ratio', label: 'R&D / Revenue', format: 'percent',
          numerator:   { source: 'income', keys: ['Research And Development'] },
          denominator: { source: 'income', keys: REVENUE_KEYS } },
        // Other Opex = (Gross Profit − Operating Income) − R&D − SG&A.
        // Numerator is computed inline since it isn't a single line item.
        { kind: 'ratio', label: 'Other Opex / Rev', format: 'percent',
          numerator:   { compute: 'other_opex' },
          denominator: { source: 'income', keys: REVENUE_KEYS } },
      ],
    },
    {
      title: 'Balance Sheet ($M)',
      rows: [
        { kind: 'raw', label: 'Total Assets',        source: 'balance', keys: ['Total Assets'], format: 'millions' },
        { kind: 'raw', label: 'Cash & Equivalents',  source: 'balance', keys: ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'], format: 'millions' },
        // Dynamic top-asset rows for this specific ticker (e.g. Goodwill, PPE)
        ...assetKeys.map<RawRow>((key) => ({
          kind: 'raw', label: key, source: 'balance', keys: [key], format: 'millions',
        })),
        { kind: 'raw', label: 'Total Debt',          source: 'balance', keys: ['Total Debt', 'Long Term Debt'], format: 'millions' },
        { kind: 'raw', label: 'Stockholders Equity', source: 'balance', keys: ['Common Stock Equity', 'Stockholders Equity'], format: 'millions' },
      ],
    },
    {
      title: 'Cash Flow ($M)',
      rows: [
        { kind: 'raw', label: 'Operating CF',  source: 'cash_flow', keys: ['Cash Flow From Continuing Operating Activities', 'Operating Cash Flow'], format: 'millions' },
        { kind: 'raw', label: 'Capex',         source: 'cash_flow', keys: ['Capital Expenditure'], format: 'millions', abs: true },
        { kind: 'raw', label: 'Free CF',       source: 'cash_flow', keys: ['Free Cash Flow'], format: 'millions' },
      ],
    },
    {
      title: 'Per Share',
      rows: [
        { kind: 'raw',   label: 'Diluted Shares (M)', source: 'income', keys: SHARES_KEYS, format: 'millions' },
        { kind: 'raw',   label: 'Diluted EPS',        source: 'income', keys: ['Diluted EPS', 'Basic EPS'], format: 'per_share' },
        // Sales Per Share = Revenue / Diluted Shares (with quarterly-shares
        // fallback for tickers whose annual income statement omits shares).
        { kind: 'ratio', label: 'Sales Per Share',    format: 'per_share',
          numerator:   { source: 'income', keys: REVENUE_KEYS },
          denominator: { compute: 'shares' } },
        // Book Value Per Share = Common Stock Equity / Diluted Shares.
        { kind: 'ratio', label: 'Book Value Per Share', format: 'per_share',
          numerator:   { source: 'balance', keys: ['Common Stock Equity', 'Stockholders Equity'] },
          denominator: { compute: 'shares' } },
      ],
    },
  ];

  // Valuation Multiples — only when we can ground prices to periods.
  // Keep the table focused on the three "static" baselines; the richer
  // set (TTM P/E, P/FCF, EV/Revenue, etc.) is better explored as charts
  // rendered separately on the ticker screen.
  if (priceByMonth.size > 0) {
    sections.push({
      title: 'Valuation Multiples',
      rows: [
        { kind: 'valuation', label: 'Static P/E', metric: 'static_pe' },
        { kind: 'valuation', label: 'Static P/S', metric: 'static_ps' },
        { kind: 'valuation', label: 'P/B',        metric: 'pb' },
      ],
    });
  }

  const onContentSizeChange = useCallback(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, []);

  // ====== Per-cell resolvers ======

  function resolveRawCell(row: RawRow, col: Column): { value: number | null; source?: string } {
    const periodDict = lookup[col.kind][row.source].get(col.period);
    if (!periodDict) return { value: null };
    const items = periodDict.items as Record<string, number | null>;
    return { value: pickFirst(items, row.keys), source: pickSource(periodDict.sources, row.keys) };
  }

  /** Compute the "Other Opex" numerator inline for a column.
   *
   *   Other Opex $ = (Gross Profit − Operating Income) − R&D − SG&A
   *
   * If a company reports S&M + G&A separately instead of SG&A combined,
   * we use the sum. R&D defaults to 0 when not reported. Returns null
   * when Gross Profit or Operating Income is missing, or when neither
   * SG&A nor the S&M+G&A breakout is available. Mirrors
   * `_other_opex_amount` in the Python ratios module. */
  function computeOtherOpex(items: Record<string, number | null>): number | null {
    const gp = pickFirst(items, ['Gross Profit']);
    const op = pickFirst(items, ['Operating Income', 'Total Operating Income As Reported']);
    if (gp == null || op == null) return null;
    const totalOpex = gp - op;
    const rd = pickFirst(items, ['Research And Development']) ?? 0;
    const sga = pickFirst(items, ['Selling General And Administration']);
    if (sga != null) return totalOpex - rd - sga;
    const sm = pickFirst(items, ['Selling And Marketing Expense']);
    const ga = pickFirst(items, ['General And Administrative Expense']);
    if (sm != null && ga != null) return totalOpex - rd - (sm + ga);
    return null;
  }

  function resolveRatioCell(row: RatioRow, col: Column): { num: number | null; den: number | null } {
    let num: number | null = null;
    if ('compute' in row.numerator) {
      // Only 'other_opex' is expressible as a numerator (type-enforced).
      const items = lookup[col.kind].income.get(col.period)?.items as Record<string, number | null> | undefined;
      if (items) num = computeOtherOpex(items);
    } else {
      const items = lookup[col.kind][row.numerator.source].get(col.period)?.items as Record<string, number | null> | undefined;
      if (items) num = pickFirst(items, row.numerator.keys);
    }

    let den: number | null = null;
    if ('compute' in row.denominator) {
      // Only 'shares' is expressible as a denominator (type-enforced).
      den = sharesForColumn(col);
    } else {
      const items = lookup[col.kind][row.denominator.source].get(col.period)?.items as Record<string, number | null> | undefined;
      if (items) den = pickFirst(items, row.denominator.keys);
    }
    return { num, den };
  }

  /** Diluted shares for the column. Tries the column's own income row
   * first; falls back to the latest quarterly value at-or-before the
   * column's period (matches Python's fallback behavior). */
  function sharesForColumn(col: Column): number | null {
    const ownItems = lookup[col.kind].income.get(col.period)?.items as Record<string, number | null> | undefined;
    const shares = ownItems ? pickFirst(ownItems, ['Diluted Average Shares', 'Basic Average Shares']) : null;
    if (shares != null) return shares;
    return latestAtOrBefore(
      [...quarterly.income_statement].sort((a, b) => a.period.localeCompare(b.period)),
      col.period,
      ['Diluted Average Shares', 'Basic Average Shares'],
    );
  }

  /** Latest known close at or before the given period (looking up by
   * YYYY-MM). Walks the priceHistory ascending and keeps the most recent
   * qualifying point. */
  function priceAtPeriod(periodISO: string): number | null {
    const month = periodISO.slice(0, 7);
    let best: number | null = null;
    for (const p of priceHistory || []) {
      if (p.close == null) continue;
      const m = p.date.slice(0, 7);
      if (m <= month) best = p.close;
      else break;
    }
    return best;
  }

  function resolveValuationCell(row: ValuationRow, col: Column): string {
    const price = priceAtPeriod(col.period);
    const shares = sharesForColumn(col);
    if (price == null || shares == null) return '—';
    const mcap = price * shares;

    switch (row.metric) {
      case 'pb': {
        const bsItems = lookup[col.kind].balance.get(col.period)?.items as Record<string, number | null> | undefined;
        const bv = bsItems ? pickFirst(bsItems, ['Common Stock Equity', 'Stockholders Equity']) : null;
        return bv == null || bv === 0 ? '—' : formatRatio(mcap / bv);
      }
      case 'static_pe': {
        const ni = latestAtOrBefore(sortedAnnualIncome, col.period, NI_KEYS);
        return ni == null || ni === 0 ? '—' : formatRatio(mcap / ni);
      }
      case 'static_ps': {
        const rev = latestAtOrBefore(sortedAnnualIncome, col.period, REVENUE_KEYS);
        return rev == null || rev === 0 ? '—' : formatRatio(mcap / rev);
      }
    }
  }

  // ====== YoY helpers ======

  function yoyForRawRow(row: RawRow, col: Column, idx: number): number | null {
    const priorIdx = col.kind === 'annual' ? idx - 1 : idx - 4;
    if (priorIdx < 0 || priorIdx >= columns.length) return null;
    const prior = columns[priorIdx];
    if (prior.kind !== col.kind) return null;
    const curr = resolveRawCell(row, col).value;
    const prev = resolveRawCell(row, prior).value;
    if (curr == null || prev == null) return null;
    return yoyDelta(row.abs ? Math.abs(curr) : curr, row.abs ? Math.abs(prev) : prev);
  }

  function yoyForRatioRow(row: RatioRow, col: Column, idx: number): number | null {
    const priorIdx = col.kind === 'annual' ? idx - 1 : idx - 4;
    if (priorIdx < 0 || priorIdx >= columns.length) return null;
    const prior = columns[priorIdx];
    if (prior.kind !== col.kind) return null;
    const currC = resolveRatioCell(row, col);
    const prevC = resolveRatioCell(row, prior);
    if (currC.num == null || currC.den == null || prevC.num == null || prevC.den == null) return null;
    if (currC.den === 0 || prevC.den === 0) return null;
    return yoyDelta(currC.num / currC.den, prevC.num / prevC.den);
  }

  function yoyTint(delta: number | null): string | undefined {
    if (delta == null) return undefined;
    if (delta >= YOY_GREEN) return c.statusOkBg;
    if (delta <= YOY_RED) return c.statusErrorBg;
    return undefined;
  }

  // ====== Render ======

  const tableHeight = Math.max(
    TABLE_HEIGHT_MIN,
    Math.min(TABLE_HEIGHT_MAX, screenH * TABLE_HEIGHT_RATIO),
  );
  const bodyHeight = tableHeight - HEADER_HEIGHT;
  const totalBodyContentHeight =
    sections.reduce((sum, s) => sum + SECTION_HEADER_HEIGHT + s.rows.length * ROW_HEIGHT, 0);

  return (
    <View>
      <View style={[styles.tableWrap, { borderColor: c.border, height: tableHeight }]}>
        {/* ===== Frozen left column ===== */}
        <View style={[styles.labelCol, { borderRightColor: c.border, width: LABEL_WIDTH }]}>
          <View style={[styles.headerCell, { borderBottomColor: c.border, height: HEADER_HEIGHT }]}>
            <Text style={[styles.headerText, { color: c.textMuted }]}>METRIC</Text>
          </View>
          {/* Labels live inside a clipped window translated by scrollY so
              they track the data body's vertical scroll without needing a
              second ScrollView (which iOS won't let us drive natively). */}
          <View style={[styles.labelBodyWindow, { height: bodyHeight }]}>
            <Animated.View
              style={{
                height: totalBodyContentHeight,
                transform: [{ translateY: Animated.multiply(scrollY, -1) }],
              }}
            >
              {sections.map((section) => (
                <View key={section.title}>
                  <View style={[styles.sectionHeader, { height: SECTION_HEADER_HEIGHT, borderBottomColor: c.border, backgroundColor: c.surface }]}>
                    <Text style={[styles.sectionHeaderText, { color: c.brand }]} numberOfLines={1}>
                      {section.title.toUpperCase()}
                    </Text>
                  </View>
                  {section.rows.map((row) => (
                    <View key={row.label} style={[styles.labelCell, { height: ROW_HEIGHT }]}>
                      <Text style={[styles.labelText, { color: c.textPrimary }]} numberOfLines={1}>
                        {row.label}
                      </Text>
                    </View>
                  ))}
                </View>
              ))}
            </Animated.View>
          </View>
        </View>

        {/* ===== Scrollable right area ===== */}
        <ScrollView
          ref={scrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          bounces
          onContentSizeChange={onContentSizeChange}
        >
          <View>
            <View style={[styles.periodHeaderRow, { borderBottomColor: c.border, height: HEADER_HEIGHT }]}>
              {columns.map((col, idx) => (
                <View
                  key={`${col.kind}-${col.period}`}
                  style={[
                    styles.cell,
                    { width: CELL_WIDTH, height: HEADER_HEIGHT },
                    idx === dividerIdx && { borderLeftWidth: 2, borderLeftColor: c.border },
                  ]}
                >
                  <Text style={[styles.headerText, { color: c.textMuted }]}>{col.label}</Text>
                </View>
              ))}
            </View>

            <Animated.ScrollView
              style={{ height: bodyHeight }}
              showsVerticalScrollIndicator
              onScroll={Animated.event(
                [{ nativeEvent: { contentOffset: { y: scrollY } } }],
                { useNativeDriver: true },
              )}
              scrollEventThrottle={16}
            >
              {sections.map((section) => (
                <View key={section.title}>
                  <View
                    style={[
                      styles.sectionHeaderSpacer,
                      {
                        height: SECTION_HEADER_HEIGHT,
                        width: CELL_WIDTH * columns.length,
                        backgroundColor: c.surface,
                        borderBottomColor: c.border,
                      },
                    ]}
                  />
                  {section.rows.map((row) => (
                    <View key={row.label} style={[styles.valueRow, { height: ROW_HEIGHT }]}>
                      {columns.map((col, idx) => {
                        let text = '—';
                        let yoy: number | null = null;
                        let source: string | undefined;

                        if (row.kind === 'raw') {
                          const r = resolveRawCell(row, col);
                          text = formatCell(r.value, row);
                          yoy = yoyForRawRow(row, col, idx);
                          source = r.source;
                        } else if (row.kind === 'ratio') {
                          const r = resolveRatioCell(row, col);
                          text = row.format === 'percent'
                            ? formatMargin(r.num, r.den)
                            : formatPerShare(r.num, r.den);
                          yoy = yoyForRatioRow(row, col, idx);
                        } else {
                          // valuation
                          text = resolveValuationCell(row, col);
                        }

                        const isYfinance = source === 'yfinance';
                        const tint = yoyTint(yoy);
                        return (
                          <View
                            // Must include `col.kind` because an annual
                            // fiscal-year-end and the matching Q4 end on
                            // the same calendar date would otherwise share
                            // a key.
                            key={`${col.kind}-${col.period}`}
                            style={[
                              styles.cell,
                              {
                                width: CELL_WIDTH,
                                height: ROW_HEIGHT,
                                backgroundColor: tint,
                              },
                              idx === dividerIdx && { borderLeftWidth: 2, borderLeftColor: c.border },
                            ]}
                          >
                            <Text
                              style={[
                                styles.cellText,
                                { color: c.textPrimary },
                                isYfinance && { fontStyle: 'italic', opacity: 0.85 },
                              ]}
                              numberOfLines={1}
                            >
                              {text}
                            </Text>
                          </View>
                        );
                      })}
                    </View>
                  ))}
                </View>
              ))}
            </Animated.ScrollView>
          </View>
        </ScrollView>
      </View>

      <View style={styles.legend}>
        <View style={[styles.legendChip, { backgroundColor: c.statusOkBg }]}>
          <Text style={[styles.legendText, { color: c.statusOkText }]}>YoY ≥ +20%</Text>
        </View>
        <View style={[styles.legendChip, { backgroundColor: c.statusErrorBg }]}>
          <Text style={[styles.legendText, { color: c.statusErrorText }]}>YoY ≤ −20%</Text>
        </View>
        <Text style={[styles.legendText, { color: c.textMuted, fontStyle: 'italic' }]}>
          italic = yfinance gap-fill
        </Text>
      </View>
    </View>
  );
}


function byPeriod(periods: Period[]): Map<string, Period> {
  return new Map(periods.map((p) => [p.period, p]));
}


const styles = StyleSheet.create({
  tableWrap: {
    flexDirection: 'row',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 6,
    overflow: 'hidden',
  },
  labelCol: {
    borderRightWidth: StyleSheet.hairlineWidth,
  },
  labelBodyWindow: {
    overflow: 'hidden',
  },
  headerCell: {
    paddingHorizontal: spacing.sm,
    justifyContent: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  periodHeaderRow: {
    flexDirection: 'row',
    borderBottomWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
  },
  sectionHeader: {
    paddingHorizontal: spacing.sm,
    justifyContent: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  sectionHeaderText: {
    fontSize: fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 0.8,
  },
  sectionHeaderSpacer: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  labelCell: {
    paddingHorizontal: spacing.sm,
    justifyContent: 'center',
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  cell: {
    paddingHorizontal: spacing.xs,
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  headerText: {
    fontSize: fontSize.xs - 1,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  labelText: {
    fontSize: fontSize.sm,
    fontWeight: '500',
  },
  cellText: {
    fontSize: fontSize.sm,
    fontVariant: ['tabular-nums'],
  },
  legend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: spacing.sm,
    alignItems: 'center',
  },
  legendChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 3,
  },
  legendText: {
    fontSize: fontSize.xs,
    letterSpacing: 0.3,
  },
});
