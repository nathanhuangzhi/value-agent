/**
 * Me tab — the account and everything that belongs to it: sign in / out,
 * custom metrics (charts next).
 */
import { Ionicons } from '@expo/vector-icons';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useRouter } from 'expo-router';

import { metricsApi, type Chart, type Metric } from '@/api/metrics';
import { SignIn } from '@/components/SignIn';
import { useAuth } from '@/hooks/useAuth';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate } from '@/utils/format';

export default function MeScreen() {
  const c = useColors();
  const { user, ready, signOut } = useAuth();
  const router = useRouter();
  const [metrics, setMetrics] = useState<Metric[] | null>(null);
  const [charts, setCharts] = useState<Chart[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [m, ch] = await Promise.all([metricsApi.list(), metricsApi.charts()]);
      setMetrics(m);
      setCharts(ch);
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);
  useEffect(() => {
    if (user) refresh(); else { setMetrics(null); setCharts([]); }
  }, [user, refresh]);

  const confirm = (title: string, run: () => Promise<unknown>) =>
    Alert.alert(`Delete "${title}"?`, undefined, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => run().then(refresh).catch((e) => setError(String(e.message ?? e))) },
    ]);

  return (
    <ScrollView style={{ backgroundColor: c.background }} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
      {!ready ? (
        <ActivityIndicator color={c.brand} />
      ) : user ? (
        <>
          <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
            <View style={styles.row}>
              <Ionicons name="person-circle-outline" size={36} color={c.brand} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.email, { color: c.textPrimary }]}>{user.email}</Text>
                <Text style={[styles.meta, { color: c.textMuted }]}>Member since {formatDate(user.created_at)}</Text>
              </View>
              <Pressable onPress={signOut} hitSlop={8}><Text style={[styles.link, { color: c.negative }]}>Sign out</Text></Pressable>
            </View>
          </View>

          <View style={styles.sectionHead}>
            <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>MY METRICS & CHARTS</Text>
          </View>
          <Pressable onPress={() => router.push('/ai')} style={[styles.designCard, { backgroundColor: c.surface, borderColor: c.border }]}>
            <Ionicons name="sparkles-outline" size={22} color={c.brand} />
            <View style={{ flex: 1 }}>
              <Text style={[styles.metricName, { color: c.textPrimary }]}>Design them in the AI chat</Text>
              <Text style={[styles.hint, { color: c.textMuted }]}>
                Say what you want to track — “track FCF margin”, “plot revenue and net cash per share for VIPS over 3 years” — the assistant writes the formula, shows you real numbers, saves it, and every company page keeps it updated as new filings arrive.
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={c.textMuted} />
          </Pressable>

          {error ? <Text style={[styles.err, { color: c.negative }]}>{error}</Text> : null}
          {metrics === null ? <ActivityIndicator color={c.brand} /> : null}
          {metrics?.map((m) => (
            <Pressable key={`m${m.id}`} onLongPress={() => confirm(m.name, () => metricsApi.remove(m.id))}
              style={[styles.metricRow, { backgroundColor: c.surface, borderColor: c.border }]}>
              <Ionicons name="calculator-outline" size={18} color={c.textMuted} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.metricName, { color: c.textPrimary }]}>{m.name}</Text>
                <Text style={[styles.mono, styles.metricExpr, { color: c.textMuted }]} numberOfLines={2}>{m.expr}</Text>
              </View>
              <Text style={[styles.fmt, { color: c.textMuted }]}>{m.format}</Text>
            </Pressable>
          ))}
          {charts.map((ch) => (
            <Pressable key={`c${ch.id}`} onLongPress={() => confirm(ch.title, () => metricsApi.removeChart(ch.id))}
              style={[styles.metricRow, { backgroundColor: c.surface, borderColor: c.border }]}>
              <Ionicons name="bar-chart-outline" size={18} color={c.textMuted} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.metricName, { color: c.textPrimary }]}>{ch.title}</Text>
                <Text style={[styles.mono, styles.metricExpr, { color: c.textMuted }]} numberOfLines={2}>
                  {ch.spec.series.map((sr) => `${sr.label}: ${sr.expr}`).join(' · ')}
                </Text>
              </View>
              <Text style={[styles.fmt, { color: c.textMuted }]}>{ch.spec.period === 'annual' ? 'FY' : 'Q'}·{ch.spec.last_n ?? 12}</Text>
            </Pressable>
          ))}
          {metrics && (metrics.length || charts.length) ? <Text style={[styles.meta, { color: c.textMuted }]}>Long-press to delete. Ask the AI to change one.</Text> : null}
        </>
      ) : (
        <SignIn intro="Your saved companies, AI conversations and custom metrics are kept with your account. Sign in with your email — no password." />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: spacing.lg, gap: spacing.md },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  email: { fontSize: fontSize.md, fontWeight: '700' },
  meta: { fontSize: fontSize.xs, marginTop: 2 },
  link: { fontSize: fontSize.sm, fontWeight: '700' },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.sm },
  eyebrow: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 1.5, borderBottomWidth: 2, paddingBottom: 4 },
  designCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.md },
  hint: { fontSize: fontSize.sm, lineHeight: 20 },
  mono: { fontFamily: 'Menlo', fontSize: fontSize.xs },
  metricRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md },
  metricName: { fontSize: fontSize.md, fontWeight: '600' },
  metricExpr: { marginTop: 2 },
  fmt: { fontSize: fontSize.xs, fontWeight: '600' },
  err: { fontSize: fontSize.sm },
});
