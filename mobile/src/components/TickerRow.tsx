import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter, useSegments } from 'expo-router';

import type { TickerRow as TickerRowData } from '@/api/types';
import { useColors, fontSize, spacing } from '@/theme/colors';
import { formatMoney, formatRatio } from '@/utils/format';

// Flex weights shared between TickerRow and TickerRowHeader so the header
// labels line up with the values beneath them. Identity (ticker + name)
// gets twice the share of each numeric column.
const COL_FLEX = {
  identity: 2,
  kpi: 1,
} as const;

export function TickerRowHeader() {
  const c = useColors();
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
      {(['Mcap', 'P/E', 'P/B', 'Q NI', 'Q OCF'] as const).map((label) => (
        <View key={label} style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
          <Text style={[styles.headerLabel, { color: c.textMuted }]}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

export function TickerRow({ row }: { row: TickerRowData }) {
  const c = useColors();
  const router = useRouter();
  const segments = useSegments();
  // If this row is somehow rendered while already on a ticker screen
  // (today: only via SplitLayout on iPad-landscape), swap the URL rather
  // than pushing so Back continues to return to the industry/digest the
  // user came from instead of walking through prior tickers.
  const isOnTicker = segments[0] === 'ticker';
  const go = () => {
    const target = `/ticker/${row.ticker}` as const;
    if (isOnTicker) {
      router.replace(target);
    } else {
      router.push(target);
    }
  };
  return (
    <Pressable
      onPress={go}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: pressed ? c.surface : c.background,
          borderBottomColor: c.border,
        },
      ]}
    >
      <View style={[styles.left, { flex: COL_FLEX.identity }]}>
        <Text style={[styles.ticker, { color: c.textPrimary }]}>{row.ticker}</Text>
        <Text
          style={[styles.name, { color: c.textMuted }]}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          {row.name}
        </Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatMoney(row.market_cap)}</Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatRatio(row.ttm_pe)}</Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatRatio(row.pb)}</Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatMoney(row.latest_q_ni)}</Text>
      </View>
      <View style={[styles.kpiCell, { flex: COL_FLEX.kpi }]}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatMoney(row.latest_q_ocf)}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  left: { minWidth: 0 },
  kpiCell: { alignItems: 'flex-end', paddingHorizontal: spacing.xs },
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
