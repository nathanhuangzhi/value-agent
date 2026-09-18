/** A saved chart rendered for one company (fetches /me/charts/{id}/data). */
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { metricsApi, type ChartData } from '@/api/metrics';
import { SeriesChart } from '@/components/SeriesChart';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

export function CustomChart({ chartId, ticker, data: given }: { chartId?: number; ticker: string; data?: ChartData }) {
  const c = useColors();
  const [data, setData] = useState<ChartData | null>(given ?? null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (given || chartId == null) return;
    let cancelled = false;
    metricsApi.chartData(chartId, ticker).then((d) => { if (!cancelled) setData(d); }).catch((e) => { if (!cancelled) setError(String(e.message ?? e)); });
    return () => { cancelled = true; };
  }, [chartId, ticker, given]);
  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
      <View style={styles.head}>
        <Text style={[styles.title, { color: c.textPrimary }]} numberOfLines={1}>{data?.title ?? 'Chart'}</Text>
        <Text style={[styles.ticker, { color: c.textMuted }]}>{ticker.toUpperCase()}</Text>
      </View>
      {error || data?.error ? (
        <Text style={[styles.err, { color: c.negative }]}>{error ?? data?.error}</Text>
      ) : !data ? (
        <ActivityIndicator color={c.brand} style={{ height: 120 }} />
      ) : (
        <SeriesChart periods={data.periods ?? []} series={data.series ?? []} period={data.period ?? 'quarterly'} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md, marginVertical: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  title: { fontSize: fontSize.md, fontWeight: '700', flex: 1 },
  ticker: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 0.5 },
  err: { fontSize: fontSize.sm },
});
