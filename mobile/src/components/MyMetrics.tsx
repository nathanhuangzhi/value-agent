/**
 * The account's custom metrics and charts for one company. `useCustom`
 * fetches both once per ticker: the metrics (and extracted series) are
 * rendered as rows of the statements table's "Custom Metrics" section by
 * the ticker page, and `MyCharts` draws the charts. Renders nothing when
 * signed out or when nothing is saved, so its section stays clean.
 */
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { metricsApi, type ChartData, type CustomTableRow, type Evaluated } from '@/api/metrics';
import { CustomChart } from '@/components/CustomChart';
import { useAuth } from '@/hooks/useAuth';
import { spacing } from '@/theme/colors';

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

export function MyCharts({ ticker }: { ticker: string }) {
  const data = useCustom(ticker);
  if (!data || data.charts.length === 0) return null;
  return <View style={styles.charts}>{data.charts.map((ch) => <CustomChart key={ch.id} ticker={ticker} data={ch} />)}</View>;
}

const styles = StyleSheet.create({
  charts: { marginBottom: spacing.sm },
});
