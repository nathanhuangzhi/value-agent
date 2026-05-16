import { StyleSheet, Text, View } from 'react-native';

import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatMoney, formatRatio } from '@/utils/format';
import type { Snapshot } from '@/api/types';

export function KPIGrid({ snapshot }: { snapshot: Snapshot }) {
  const c = useColors();
  const items = [
    { label: 'MARKET CAP', value: formatMoney(snapshot.market_cap) },
    { label: 'TTM P/E', value: formatRatio(snapshot.ttm_pe) },
    { label: 'P/B', value: formatRatio(snapshot.pb) },
    { label: 'P/S', value: formatRatio(snapshot.ps) },
    { label: 'TTM P/OCF', value: formatRatio(snapshot.ttm_pocf) },
  ];
  return (
    <View style={styles.grid}>
      {items.map((it) => (
        <View
          key={it.label}
          style={[
            styles.cell,
            { backgroundColor: c.surface, borderColor: c.border },
          ]}
        >
          <Text style={[styles.label, { color: c.textMuted }]}>{it.label}</Text>
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
    flexGrow: 1,
    flexBasis: '30%',
    minWidth: 90,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.md,
  },
  label: {
    fontSize: fontSize.xs - 1,
    letterSpacing: 1,
    fontWeight: '600',
  },
  value: {
    fontSize: fontSize.lg,
    fontWeight: '700',
    marginTop: 4,
    fontVariant: ['tabular-nums'],
  },
});
