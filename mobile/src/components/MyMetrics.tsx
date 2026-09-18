/**
 * "My metrics" — the account's custom metrics evaluated for one company:
 * a horizontal strip of name + latest value, with the last quarters as a
 * tiny row underneath. Tapping a metric expands its series.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { formatMetric, metricsApi, type Evaluated } from '@/api/metrics';
import { useAuth } from '@/hooks/useAuth';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function MyMetrics({ ticker }: { ticker: string }) {
  const c = useColors();
  const { user } = useAuth();
  const [rows, setRows] = useState<Evaluated[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    if (!user) { setRows(null); return; }
    let cancelled = false;
    metricsApi.forTicker(ticker).then((r) => { if (!cancelled) setRows(r.metrics); }).catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, [ticker, user]);

  if (!user || (rows !== null && rows.length === 0)) return null;
  return (
    <View style={styles.wrap}>
      <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>MY METRICS</Text>
      {rows === null ? <ActivityIndicator color={c.brand} style={{ marginTop: spacing.md }} /> : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.strip}>
          {rows.map((m) => {
            const expanded = open === m.id;
            return (
              <Pressable key={m.id} onPress={() => setOpen(expanded ? null : m.id)}
                style={[styles.tile, { backgroundColor: c.surface, borderColor: c.border }, expanded && { borderColor: c.brand }]}>
                <Text style={[styles.name, { color: c.textMuted }]} numberOfLines={1}>{m.name}</Text>
                {m.error ? (
                  <Text style={[styles.err, { color: c.negative }]} numberOfLines={2}>{m.error}</Text>
                ) : (
                  <Text style={[styles.value, { color: c.textPrimary }]}>{formatMetric(m.latest, m.format)}</Text>
                )}
                {expanded && !m.error ? (
                  <View style={styles.series}>
                    {m.series.map((p) => (
                      <View key={p.period} style={styles.seriesRow}>
                        <Text style={[styles.period, { color: c.textMuted }]}>{p.period.slice(0, 7)}</Text>
                        <Text style={[styles.seriesVal, { color: p.value == null ? c.textMuted : c.textPrimary }]}>{formatMetric(p.value, m.format)}</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </Pressable>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  eyebrow: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 1.5, borderBottomWidth: 2, paddingBottom: 4, alignSelf: 'flex-start', marginBottom: spacing.sm },
  strip: { gap: spacing.sm, paddingVertical: 2 },
  tile: { minWidth: 120, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md, gap: 2 },
  name: { fontSize: fontSize.xs, fontWeight: '600' },
  value: { fontSize: fontSize.lg, fontWeight: '700', fontVariant: ['tabular-nums'] },
  err: { fontSize: fontSize.xs },
  series: { marginTop: spacing.sm, gap: 2 },
  seriesRow: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  period: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  seriesVal: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
});
