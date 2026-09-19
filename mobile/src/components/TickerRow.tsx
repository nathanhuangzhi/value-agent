import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter, useSegments } from 'expo-router';

import type { TickerRow as TickerRowData } from '@/api/types';
import { MiniBars } from './MiniBars';
import { PriceSparkline } from './PriceSparkline';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useColors, fontSize, spacing } from '@/theme/colors';
import { formatMoney, formatRatio } from '@/utils/format';

// Flex weights shared between TickerRow and TickerRowHeader so the header
// labels line up with the values beneath them. Identity (ticker + name)
// gets twice the share of each numeric column.
const COL_FLEX = {
  identity: 2,
  kpi: 1,
} as const;

export function TickerRowHeader({ showChart = false }: { showChart?: boolean }) {
  const c = useColors();
  const firstCol = showChart ? '1Y Price' : 'Mcap';
  return (
    <View
      style={[
        styles.row,
        {
          backgroundColor: c.surface,
          borderBottomColor: c.border,
          borderBottomWidth: StyleSheet.hairlineWidth,
        },
      ]}
    >
      <View style={[styles.left, { flex: COL_FLEX.identity }]}>
        <Text style={[styles.headerLabel, { color: c.textMuted }]}>Ticker</Text>
      </View>
      {([firstCol, 'P/QE', 'P/QFCF', 'TTM P/E', 'Mcap'] as const).map((label) => (
        <View key={label} style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
          <Text style={[styles.headerLabel, { color: c.textMuted }]}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

export function TickerRow({
  row,
  highlighted = false,
  showChart = false,
  chartDelay = 0,
  onLongPress,
}: {
  row: TickerRowData;
  highlighted?: boolean;
  showChart?: boolean;
  chartDelay?: number;
  /** Optional — the Saved tab uses a long-press to offer removal. */
  onLongPress?: () => void;
}) {
  const c = useColors();
  const router = useRouter();
  const segments = useSegments();
  const device = useDeviceClass();
  // If this row is somehow rendered while already on a ticker screen
  // (today: only via SplitLayout on iPad-landscape), swap the URL rather
  // than pushing so Back continues to return to the industry/digest the
  // user came from instead of walking through prior tickers.
  // On the phone every company opens as a pushed page (so Back always
  // exists); only the iPad split layout swaps the right pane in place.
  const inSplitPane = segments[0] === 'ticker' && device === 'tablet-landscape';
  const go = () => {
    const target = `/ticker/${row.ticker}` as const;
    if (inSplitPane) router.replace(target);
    else router.push(target);
  };
  return (
    <Pressable
      onPress={go}
      onLongPress={onLongPress}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: pressed
            ? c.surface
            : highlighted
              ? c.statusOkBg
              : c.background,
          borderBottomColor: c.border,
          borderLeftColor: highlighted ? c.brand : 'transparent',
        },
      ]}
    >
      <View style={[styles.left, { flex: COL_FLEX.identity }]}>
        <Text style={[styles.ticker, { color: highlighted ? c.brand : c.textPrimary }]}>{row.ticker}</Text>
        <Text
          style={[styles.name, { color: c.textMuted }]}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          {row.name}
        </Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        {showChart ? (
          <PriceSparkline ticker={row.ticker} delay={chartDelay} />
        ) : (
          <Kpi>{formatMoney(row.market_cap)}</Kpi>
        )}
      </View>
      {/* Last four quarters, annualised: price / quarterly earnings and price / quarterly FCF. */}
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <MiniBars values={lastFour(row.quarterly_multiples, 'pqe')} />
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <MiniBars values={lastFour(row.quarterly_multiples, 'pqfcf')} />
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Kpi>{formatRatio(row.ttm_pe)}</Kpi>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Kpi>{formatMoney(row.market_cap)}</Kpi>
      </View>
    </Pressable>
  );
}

/** Always four slots, oldest → newest, padded with nulls when fewer quarters exist. */
function lastFour(series: TickerRowData['quarterly_multiples'] | undefined, key: 'pqe' | 'pqfcf'): (number | null)[] {
  const vals = (series ?? []).slice(-4).map((q) => q[key] ?? null);
  while (vals.length < 4) vals.unshift(null);
  return vals;
}

/** A numeric cell: always one line — the font shrinks (down to 70%) rather than wrapping. */
function Kpi({ children }: { children: string }) {
  const c = useColors();
  return (
    <Text style={[styles.kpi, { color: c.textPrimary }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
      {children}
    </Text>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    // Constant left border (transparent unless highlighted) so the
    // last-viewed highlight never shifts row content. The header shares
    // this style, so columns stay aligned.
    borderLeftWidth: 3,
  },
  left: { minWidth: 0 },
  kpiCell: { alignItems: 'flex-end', paddingHorizontal: 2, minWidth: 0 },
  ticker: { fontSize: fontSize.md, fontWeight: '700' },
  name: { fontSize: fontSize.xs, marginTop: 2 },
  kpi: { fontSize: fontSize.sm, fontVariant: ['tabular-nums'] },
  headerLabel: {
    fontSize: fontSize.xs - 1,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
});
