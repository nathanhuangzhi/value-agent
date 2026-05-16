import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import type { TickerRow as TickerRowData } from '@/api/types';
import { useColors, fontSize, spacing } from '@/theme/colors';
import { formatMoney, formatRatio } from '@/utils/format';
import { StatusBadge } from './StatusBadge';

export function TickerRow({ row }: { row: TickerRowData }) {
  const c = useColors();
  const router = useRouter();
  return (
    <Pressable
      onPress={() => router.push(`/ticker/${row.ticker}`)}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: pressed ? c.surface : c.background,
          borderBottomColor: c.border,
        },
      ]}
    >
      <View style={styles.left}>
        <Text style={[styles.ticker, { color: c.textPrimary }]}>{row.ticker}</Text>
        <Text
          style={[styles.name, { color: c.textMuted }]}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          {row.name}
        </Text>
      </View>
      <View style={styles.middle}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatMoney(row.market_cap)}</Text>
        <Text style={[styles.kpiLabel, { color: c.textMuted }]}>mcap</Text>
      </View>
      <View style={styles.middle}>
        <Text style={[styles.kpi, { color: c.textPrimary }]}>{formatRatio(row.ttm_pe)}</Text>
        <Text style={[styles.kpiLabel, { color: c.textMuted }]}>P/E</Text>
      </View>
      <View style={styles.right}>
        <StatusBadge status={row.status} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  left: { flex: 2, minWidth: 0 },
  middle: { flex: 1, alignItems: 'flex-end', paddingHorizontal: spacing.sm },
  right: { width: 60, alignItems: 'flex-end' },
  ticker: { fontSize: fontSize.md, fontWeight: '700' },
  name: { fontSize: fontSize.xs, marginTop: 2 },
  kpi: { fontSize: fontSize.sm, fontWeight: '600', fontVariant: ['tabular-nums'] },
  kpiLabel: { fontSize: fontSize.xs - 1, marginTop: 1, letterSpacing: 0.5 },
});
