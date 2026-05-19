/**
 * 2×2 grid of valuation charts for the ticker detail screen. Matches the
 * web report's `_chart_valuation_monthly` layout: Stock Price (top-left),
 * Static P/E (top-right), Static P/S (bottom-left), P/B (bottom-right).
 *
 * The component composes its own valuation history from the same data
 * the rest of the screen consumes (annual + quarterly statements + price
 * history). The chart series are derived once via `useMemo` so toggling
 * between tickers doesn't recompute on every render.
 */
import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { PricePoint, Statements } from '@/api/types';
import { MiniLineChart, SeriesPoint } from './MiniLineChart';
import { useColors, spacing } from '@/theme/colors';
import { formatRatio, formatStockPrice } from '@/utils/format';
import { computeValuationHistory } from '@/utils/valuationHistory';


type Props = {
  annual: Statements;
  quarterly: Statements;
  priceHistory?: PricePoint[];
};


export function ValuationGrid({ annual, quarterly, priceHistory }: Props) {
  const c = useColors();

  // Build the 4 series once per (statements, priceHistory) change.
  const series = useMemo(() => {
    const history = computeValuationHistory(annual, quarterly, priceHistory || []);
    const price: SeriesPoint[] = (priceHistory || [])
      .filter((p) => p.close != null)
      .map((p) => ({ date: p.date, value: p.close! }));
    const pe: SeriesPoint[] = history
      .filter((h) => h.static_pe != null)
      .map((h) => ({ date: h.date, value: h.static_pe! }));
    const ps: SeriesPoint[] = history
      .filter((h) => h.static_ps != null)
      .map((h) => ({ date: h.date, value: h.static_ps! }));
    const pb: SeriesPoint[] = history
      .filter((h) => h.pb != null)
      .map((h) => ({ date: h.date, value: h.pb! }));
    return { price, pe, ps, pb };
  }, [annual, quarterly, priceHistory]);

  // Use `flexBasis` per cell + a gap so each chart is exactly half the
  // row width regardless of phone width.
  return (
    <View style={styles.grid}>
      <View style={styles.cell}>
        <MiniLineChart title="STOCK PRICE" data={series.price} color={c.brand} format={formatStockPrice} />
      </View>
      <View style={styles.cell}>
        <MiniLineChart title="STATIC P/E" data={series.pe} color={c.brand} format={formatRatio} />
      </View>
      <View style={styles.cell}>
        <MiniLineChart title="STATIC P/S" data={series.ps} color={c.brand} format={formatRatio} />
      </View>
      <View style={styles.cell}>
        <MiniLineChart title="P/B" data={series.pb} color={c.brand} format={formatRatio} />
      </View>
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
    // 50% minus half the gap so two cells fit per row with the gap between.
    flexBasis: `48%`,
    flexGrow: 1,
  },
});
