/** One saved metric for one company, as a compact card (used inline in replies). */
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { formatMetric, metricsApi, type Evaluated } from '@/api/metrics';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function MetricTile({ metricId, ticker }: { metricId: number; ticker: string }) {
  const c = useColors();
  const [m, setM] = useState<Evaluated | null | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    metricsApi.forTicker(ticker)
      .then((r) => { if (!cancelled) setM(r.metrics.find((x) => x.id === metricId) ?? null); })
      .catch(() => { if (!cancelled) setM(null); });
    return () => { cancelled = true; };
  }, [metricId, ticker]);
  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
      {m === undefined ? <ActivityIndicator color={c.brand} /> : m === null ? (
        <Text style={[styles.err, { color: c.negative }]}>metric #{metricId} not found</Text>
      ) : (
        <>
          <Text style={[styles.name, { color: c.textMuted }]}>{m.name} · {ticker.toUpperCase()}</Text>
          {m.error ? <Text style={[styles.err, { color: c.negative }]}>{m.error}</Text>
            : <Text style={[styles.value, { color: c.textPrimary }]}>{formatMetric(m.latest, m.format)}</Text>}
          {!m.error ? (
            <View style={styles.series}>
              {m.series.map((p) => (
                <View key={p.period} style={styles.cell}>
                  <Text style={[styles.cellVal, { color: p.value == null ? c.textMuted : c.textPrimary }]} numberOfLines={1} adjustsFontSizeToFit>{formatMetric(p.value, m.format)}</Text>
                  <Text style={[styles.cellPeriod, { color: c.textMuted }]}>{p.period.slice(2, 7)}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md, marginVertical: spacing.sm, gap: 2 },
  name: { fontSize: fontSize.xs, fontWeight: '600' },
  value: { fontSize: 22, fontWeight: '700', fontVariant: ['tabular-nums'] },
  err: { fontSize: fontSize.sm },
  series: { flexDirection: 'row', gap: 4, marginTop: 6 },
  cell: { flex: 1, alignItems: 'center' },
  cellVal: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  cellPeriod: { fontSize: 9, marginTop: 2 },
});
