/**
 * Snapshot KPI grid for the ticker detail screen. Renders the same 16
 * headline numbers the web report shows: market cap, 8 valuation
 * multiples, 6 profitability/health ratios, and the dividend rate.
 *
 * Cells lay out in a flex wrap — 3 cells per row on most phones, 4 on
 * wider screens. Each cell shows the label in muted small caps and the
 * value in primary text underneath. Empty / non-meaningful values
 * render as "—" rather than "0" or "n/a".
 */
import { StyleSheet, Text, View } from 'react-native';

import type { Snapshot } from '@/api/types';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatMoney, formatRatio } from '@/utils/format';


function formatPctOneDecimal(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  const v = n * 100;
  return Math.abs(v) < 10 ? `${v.toFixed(1)}%` : `${v.toFixed(0)}%`;
}

function formatDividend(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  if (n === 0) return '$0';
  return `$${n.toFixed(2)}`;
}


export function KPIGrid({ snapshot }: { snapshot: Snapshot }) {
  const c = useColors();
  const device = useDeviceClass();
  // On a wider screen we can fit more cells per row without squeezing the
  // 16-char "Operating Margin" label. flexBasis tuned to 5 / 6 / 3 cells
  // respectively (with the gap accounted for) so flex wrap behaves.
  const flexBasis = device === 'tablet-landscape' ? '16%'
                   : device === 'tablet'           ? '19%'
                   : '30%';

  // Labels intentionally match the web `render_snapshot()` pairs list so
  // a user comparing the email/web report to the app sees identical
  // wording. Abbreviated forms (P/B, ROE, etc.) were a mistake — labels
  // fit fine at full length on the 3-cell-per-row grid.
  const items: { label: string; value: string }[] = [
    // Headline
    { label: 'Market Cap',       value: formatMoney(snapshot.market_cap) },
    // Valuation multiples (the price-paid-vs-fundamentals view)
    { label: 'TTM P/E',          value: formatRatio(snapshot.ttm_pe) },
    { label: 'Static P/E',       value: formatRatio(snapshot.static_pe) },
    { label: 'EV/Revenue',       value: formatRatio(snapshot.ev_revenue) },
    { label: 'Price/Book',       value: formatRatio(snapshot.pb) },
    { label: 'Price/Sales',      value: formatRatio(snapshot.ps) },
    { label: 'P/FCF',            value: formatRatio(snapshot.p_fcf) },
    { label: 'P/OCF',            value: formatRatio(snapshot.ttm_pocf) },
    // Health + profitability
    { label: 'Debt/Asset',       value: formatPctOneDecimal(snapshot.debt_asset) },
    { label: 'Gross Margin',     value: formatPctOneDecimal(snapshot.gross_margin) },
    { label: 'Operating Margin', value: formatPctOneDecimal(snapshot.op_margin) },
    { label: 'Profit Margin',    value: formatPctOneDecimal(snapshot.net_margin) },
    { label: 'Return on Equity', value: formatPctOneDecimal(snapshot.roe) },
    { label: 'Return on Assets', value: formatPctOneDecimal(snapshot.roa) },
    // Shareholder yield
    { label: 'Dividend Rate',    value: formatDividend(snapshot.dividend_rate) },
  ];

  return (
    <View style={styles.grid}>
      {items.map((it) => (
        <View
          key={it.label}
          style={[
            styles.cell,
            { backgroundColor: c.surface, borderColor: c.border, flexBasis },
          ]}
        >
          <Text style={[styles.label, { color: c.textMuted }]}>{it.label.toUpperCase()}</Text>
          <Text style={[styles.value, { color: c.textPrimary }]}>{it.value}</Text>
        </View>
      ))}
    </View>
  );
}


const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  cell: {
    // flexBasis is set dynamically (30% phone / 19% tablet / 16% tablet-landscape).
    // flexGrow:1 lets a partial last row fill the available width.
    flexGrow: 1,
    minWidth: 100,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.sm,
  },
  label: {
    fontSize: fontSize.xs - 1,
    letterSpacing: 1,
    fontWeight: '600',
  },
  value: {
    fontSize: fontSize.md,
    fontWeight: '700',
    marginTop: 4,
    fontVariant: ['tabular-nums'],
  },
});
