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
import { Animated, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PricePoint, Statements } from '@/api/types';
import { formatMetric } from '@/api/metrics';
import { useColors, fontSize, spacing } from '@/theme/colors';
import {
  CELL_WIDTH,
  HEADER_HEIGHT,
  LABEL_WIDTH,
  MAX_ANNUAL,
  MAX_QUARTERLY,
  NI_KEYS,
  REVENUE_KEYS,
  ROW_HEIGHT,
  SECTION_HEADER_HEIGHT,
  SHARES_KEYS,
  YOY_GREEN,
  YOY_RED,
  byPeriod,
  computeHistoricalTableColumns,
  fyLabel,
  quarterLabel,
  formatCell,
  formatMargin,
  formatPerShare,
  formatRatio,
  latestAtOrBefore,
  pickFirst,
  pickSource,
  topAssetKeys,
  topLiabilityKeys,
  yoyDelta,
  type Column,
  type RatioRow,
  type CustomRow,
  type RawRow,
  type Row,
  type Section,
  type ValuationRow,
} from '@/lib/historicalTable';

export { computeHistoricalTableColumns };
export const HISTORICAL_TABLE_HEADER_HEIGHT = HEADER_HEIGHT;
export const HISTORICAL_TABLE_LABEL_WIDTH = LABEL_WIDTH;
export const HISTORICAL_TABLE_CELL_WIDTH = CELL_WIDTH;


type Props = {
  statements: Statements;
  quarterly: Statements;
  priceHistory?: PricePoint[];
  /** When provided, the table's body horizontal-scroll position feeds
   * into this Animated.Value via Animated.event. The ticker page uses
   * it to drive a sticky FY/Q overlay's translateX so the overlay
   * tracks horizontal panning. */
  externalScrollX?: Animated.Value;
  /** Multiply money / per-share cells by this before display. 1 (default)
   * shows the USD figures the API serves; a non-USD filer's native
   * currency is `currency.per_usd`. Ratio rows are unaffected. */
  fxFactor?: number;
  /** Unit label for the $-sections, e.g. 'USD' or 'CNY'. */
  currencyLabel?: string;
  /** The account's metrics and extracted series, as a section above the statements. */
  customRows?: CustomRow[];
};


export function HistoricalTable({ statements, quarterly, priceHistory, externalScrollX, fxFactor = 1, currencyLabel = 'USD', customRows = [] }: Props) {
  const c = useColors();
  const scrollRef = useRef<ScrollView>(null);

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

  // Every non-cash asset class present (receivables, inventory, PPE,
  // goodwill, intangibles, long-term investments…), largest first,
  // determined once per ticker from the most recent balance sheet.
  const assetKeys = useMemo(
    () => topAssetKeys(statements.balance_sheet, quarterly.balance_sheet),
    [statements.balance_sheet, quarterly.balance_sheet],
  );
  // Top 3 liability lines (e.g. ['Long Term Debt', 'Accounts Payable',
  // 'Deferred Revenue']) — the liability-side counterpart of assetKeys.
  const liabilityKeys = useMemo(
    () => topLiabilityKeys(statements.balance_sheet, quarterly.balance_sheet),
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

  const onContentSizeChange = useCallback(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, []);

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
    ...(customRows.length ? [{ title: 'Custom Metrics', rows: customRows as Row[] }] : []),
    {
      title: `Income Statement (${currencyLabel})`,
      rows: [
        { kind: 'raw', label: 'Revenue',          source: 'income', keys: ['Total Revenue', 'Operating Revenue'], format: 'money' },
        { kind: 'raw', label: 'Gross Profit',     source: 'income', keys: ['Gross Profit'], format: 'money' },
        { kind: 'raw', label: 'Operating Income', source: 'income', keys: ['Operating Income', 'Total Operating Income As Reported'], format: 'money' },
        { kind: 'raw', label: 'Net Income',       source: 'income', keys: ['Net Income', 'Net Income Common Stockholders'], format: 'money' },
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
      title: `Balance Sheet (${currencyLabel})`,
      rows: [
        { kind: 'raw', label: 'Total Assets',        source: 'balance', keys: ['Total Assets'], format: 'money' },
        { kind: 'raw', label: 'Cash, STI & Restricted', source: 'balance', keys: ['Cash Cash Equivalents And Short Term Investments', 'Cash And Cash Equivalents'], format: 'money' },
        // Dynamic asset-class rows for this ticker, largest first
        ...assetKeys.map<RawRow>((key) => ({
          kind: 'raw', label: key, source: 'balance', keys: [key], format: 'money',
        })),
        { kind: 'raw', label: 'Total Liabilities',   source: 'balance', keys: ['Total Liabilities'], format: 'money', dividerAbove: true },
        // Dynamic top-3 liability rows, largest first (e.g. LT debt, payables,
        // deferred revenue). Interest-bearing "Total Debt" still feeds the
        // snapshot ratios but isn't listed here — it overlaps these rows.
        ...liabilityKeys.map<RawRow>((key) => ({
          kind: 'raw', label: key, source: 'balance', keys: [key], format: 'money',
        })),
        { kind: 'raw', label: 'Stockholders Equity', source: 'balance', keys: ['Common Stock Equity', 'Stockholders Equity'], format: 'money', dividerAbove: true },
      ],
    },
    {
      title: `Cash Flow (${currencyLabel})`,
      rows: [
        { kind: 'raw', label: 'Operating CF',  source: 'cash_flow', keys: ['Cash Flow From Continuing Operating Activities', 'Operating Cash Flow'], format: 'money' },
        { kind: 'raw', label: 'Capex',         source: 'cash_flow', keys: ['Capital Expenditure'], format: 'money', abs: true },
        { kind: 'raw', label: 'Free CF',       source: 'cash_flow', keys: ['Free Cash Flow'], format: 'money' },
      ],
    },
    {
      title: 'Per Share',
      rows: [
        { kind: 'raw',   label: 'Diluted Shares',     source: 'income', keys: SHARES_KEYS, format: 'shares' },
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

  return (
    <View>
      <View style={[styles.tableWrap, { borderColor: c.border }]}>
        {/* ===== Frozen left column ===== */}
        <View style={[styles.labelCol, { borderRightColor: c.border, width: LABEL_WIDTH }]}>
          <View style={[styles.headerCell, { borderBottomColor: c.border, height: HEADER_HEIGHT }]}>
            <Text style={[styles.headerText, { color: c.textMuted }]}>METRIC</Text>
          </View>
          {sections.map((section) => (
            <View key={section.title}>
              <View style={[styles.sectionHeader, { height: SECTION_HEADER_HEIGHT, borderBottomColor: c.border, backgroundColor: c.surface }]}>
                <Text style={[styles.sectionHeaderText, { color: c.brand }]} numberOfLines={1}>
                  {section.title.toUpperCase()}
                </Text>
              </View>
              {section.rows.map((row) => (
                <View
                  key={row.label}
                  style={[styles.labelCell, { height: ROW_HEIGHT },
                    row.kind === 'raw' && row.dividerAbove ? { borderTopWidth: 1, borderTopColor: c.border } : null]}
                >
                  <Text style={[styles.labelText, { color: c.textPrimary }]} numberOfLines={1}>
                    {row.label}
                  </Text>
                </View>
              ))}
            </View>
          ))}
        </View>

        {/* ===== Horizontally scrollable right area ===== */}
        <ScrollView
          ref={scrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          bounces
          onContentSizeChange={onContentSizeChange}
          onScroll={
            externalScrollX
              ? Animated.event(
                  [{ nativeEvent: { contentOffset: { x: externalScrollX } } }],
                  { useNativeDriver: false },
                )
              : undefined
          }
          scrollEventThrottle={externalScrollX ? 16 : undefined}
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
                  <View
                    key={row.label}
                    style={[styles.valueRow, { height: ROW_HEIGHT },
                      row.kind === 'raw' && row.dividerAbove ? { borderTopWidth: 1, borderTopColor: c.border } : null]}
                  >
                    {columns.map((col, idx) => {
                      let text = '—';
                      let yoy: number | null = null;
                      let source: string | undefined;

                      if (row.kind === 'raw') {
                        const r = resolveRawCell(row, col);
                        text = formatCell(r.value, row, fxFactor);
                        yoy = yoyForRawRow(row, col, idx);
                        source = r.source;
                      } else if (row.kind === 'ratio') {
                        const r = resolveRatioCell(row, col);
                        text = row.format === 'percent'
                          ? formatMargin(r.num, r.den)
                          : formatPerShare(r.num, r.den, fxFactor);
                        yoy = yoyForRatioRow(row, col, idx);
                      } else if (row.kind === 'custom') {
                        const v = (col.kind === 'annual' ? row.annual : row.quarterly)[col.period] ?? null;
                        const money = row.format === 'money' && v != null ? v * fxFactor : v;
                        text = formatMetric(money, row.format);
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


/**
 * Renders just the [METRIC label cell + FY/Q period row] portion of the
 * historical table. Designed for the ticker page to position absolutely
 * at the top of the screen as the user scrolls past the natural table.
 *
 * The FY/Q row sits inside a clipped window whose contents are
 * horizontally translated by `-scrollX` so the visible period labels
 * stay in sync with whatever periods the body table has panned to.
 */
export function HistoricalTablePeriodHeader({
  columns,
  dividerIdx,
  scrollX,
}: {
  columns: Column[];
  dividerIdx: number;
  scrollX: Animated.Value;
}) {
  const c = useColors();
  const totalWidth = CELL_WIDTH * columns.length;
  return (
    <View style={[stickyStyles.row, { backgroundColor: c.background }]}>
      <View
        style={[
          stickyStyles.metricCell,
          {
            width: LABEL_WIDTH,
            height: HEADER_HEIGHT,
            borderRightColor: c.border,
            borderBottomColor: c.border,
            backgroundColor: c.background,
          },
        ]}
      >
        <Text style={[styles.headerText, { color: c.textMuted }]}>METRIC</Text>
      </View>
      <View
        style={[
          stickyStyles.periodWindow,
          {
            height: HEADER_HEIGHT,
            borderBottomColor: c.border,
            backgroundColor: c.background,
          },
        ]}
      >
        <Animated.View
          style={{
            flexDirection: 'row',
            width: totalWidth,
            height: HEADER_HEIGHT,
            transform: [{ translateX: Animated.multiply(scrollX, -1) }],
          }}
        >
          {columns.map((col, idx) => (
            <View
              key={`${col.kind}-${col.period}`}
              style={[
                styles.cell,
                { width: CELL_WIDTH, height: HEADER_HEIGHT },
                idx === dividerIdx && {
                  borderLeftWidth: 2,
                  borderLeftColor: c.border,
                },
              ]}
            >
              <Text style={[styles.headerText, { color: c.textMuted }]}>
                {col.label}
              </Text>
            </View>
          ))}
        </Animated.View>
      </View>
    </View>
  );
}


const stickyStyles = StyleSheet.create({
  row: {
    flexDirection: 'row',
  },
  metricCell: {
    paddingHorizontal: spacing.sm,
    justifyContent: 'center',
    borderRightWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  periodWindow: {
    flex: 1,
    overflow: 'hidden',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
});


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
