/**
 * The account's custom metrics and charts, evaluated for one company.
 * `useCustom` fetches once per ticker; `MyMetricsStrip` shows the metrics
 * as a horizontal strip of value cards (tap to expand the series);
 * `MyCharts` renders each chart. Both render nothing when signed out or
 * when there's nothing saved, so the sections they sit in stay clean.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { formatMetric, metricsApi, type ChartData, type CustomTableRow, type Evaluated } from '@/api/metrics';
import { CustomChart } from '@/components/CustomChart';
import { useAuth } from '@/hooks/useAuth';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

type Custom = { metrics: Evaluated[]; charts: ChartData[]; rows: CustomTableRow[] };
const cache = new Map<string, Custom>();

export function useCustom(ticker: string): Custom | null {
  const { user } = useAuth();
  const [data, setData] = useState<Custom | null>(cache.get(ticker) ?? null);
  useEffect(() => {
    if (!user) { setData(null); return; }
    let cancelled = false;
    metricsApi.forTicker(ticker)
      .then((r) => { const v = { metrics: r.metrics, charts: r.charts ?? [], rows: r.rows ?? [] }; cache.set(ticker, v); if (!cancelled) setData(v); })
      .catch(() => { if (!cancelled) setData({ metrics: [], charts: [], rows: [] }); });
    return () => { cancelled = true; };
  }, [ticker, user]);
  return user ? data : null;
}

export function MyMetricsStrip({ ticker }: { ticker: string }) {
  const c = useColors();
  const data = useCustom(ticker);
  const [open, setOpen] = useState<number | null>(null);
  const { user } = useAuth();
  if (!user) return null;
  if (data === null) return <ActivityIndicator color={c.brand} style={{ marginVertical: spacing.sm }} />;
  if (data.metrics.length === 0) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.strip}>
      {data.metrics.map((m) => {
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
  );
}

export function MyCharts({ ticker }: { ticker: string }) {
  const data = useCustom(ticker);
  if (!data || data.charts.length === 0) return null;
  return <View style={styles.charts}>{data.charts.map((ch) => <CustomChart key={ch.id} ticker={ticker} data={ch} />)}</View>;
}

const styles = StyleSheet.create({
  strip: { gap: spacing.sm, paddingVertical: 2, marginBottom: spacing.md },
  tile: { minWidth: 120, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md, gap: 2 },
  name: { fontSize: fontSize.xs, fontWeight: '600' },
  value: { fontSize: fontSize.lg, fontWeight: '700', fontVariant: ['tabular-nums'] },
  err: { fontSize: fontSize.xs },
  series: { marginTop: spacing.sm, gap: 2 },
  seriesRow: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  period: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  seriesVal: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  charts: { marginBottom: spacing.sm },
});
