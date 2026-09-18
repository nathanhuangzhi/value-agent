/**
 * Me tab — the account and everything that belongs to it: sign in / out,
 * custom metrics (charts next).
 */
import { Ionicons } from '@expo/vector-icons';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { metricsApi, type Metric } from '@/api/metrics';
import { MetricEditor } from '@/components/MetricEditor';
import { SignIn } from '@/components/SignIn';
import { useAuth } from '@/hooks/useAuth';
import { useSaved } from '@/hooks/useSaved';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatDate } from '@/utils/format';

export default function MeScreen() {
  const c = useColors();
  const { user, ready, signOut } = useAuth();
  const { tickers: saved } = useSaved();
  const [metrics, setMetrics] = useState<Metric[] | null>(null);
  const [editing, setEditing] = useState<Metric | null | 'new'>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setMetrics(await metricsApi.list());
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);
  useEffect(() => {
    if (user) refresh(); else setMetrics(null);
  }, [user, refresh]);

  const remove = (m: Metric) =>
    Alert.alert(`Delete "${m.name}"?`, undefined, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => metricsApi.remove(m.id).then(refresh).catch((e) => setError(String(e.message ?? e))) },
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
            <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>MY METRICS</Text>
            {editing === null ? (
              <Pressable onPress={() => setEditing('new')} hitSlop={8} style={[styles.newBtn, { borderColor: c.brand }]}>
                <Ionicons name="add" size={16} color={c.brand} />
                <Text style={[styles.newText, { color: c.brand }]}>New</Text>
              </Pressable>
            ) : null}
          </View>
          <Text style={[styles.hint, { color: c.textMuted }]}>
            Your own formulas over any company&apos;s statements — e.g. <Text style={styles.mono}>fcf.ttm / revenue.ttm</Text> or{' '}
            <Text style={styles.mono}>(cash + sti - total_debt) / shares</Text>. They show on every company page.
          </Text>

          {editing !== null ? (
            <MetricEditor
              metric={editing === 'new' ? null : editing}
              sampleTicker={saved[0] ?? 'VIPS'}
              onSaved={() => { setEditing(null); refresh(); }}
              onCancel={() => setEditing(null)}
            />
          ) : null}

          {error ? <Text style={[styles.err, { color: c.negative }]}>{error}</Text> : null}
          {metrics === null ? <ActivityIndicator color={c.brand} /> : metrics.length === 0 && editing === null ? (
            <Text style={[styles.hint, { color: c.textMuted }]}>No metrics yet.</Text>
          ) : (
            metrics.map((m) => (
              <Pressable key={m.id} onPress={() => setEditing(m)} onLongPress={() => remove(m)}
                style={[styles.metricRow, { backgroundColor: c.surface, borderColor: c.border }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.metricName, { color: c.textPrimary }]}>{m.name}</Text>
                  <Text style={[styles.mono, styles.metricExpr, { color: c.textMuted }]} numberOfLines={2}>{m.expr}</Text>
                </View>
                <Text style={[styles.fmt, { color: c.textMuted }]}>{m.format}</Text>
                <Ionicons name="chevron-forward" size={16} color={c.textMuted} />
              </Pressable>
            ))
          )}
          {metrics && metrics.length ? <Text style={[styles.meta, { color: c.textMuted }]}>Tap to edit · long-press to delete.</Text> : null}
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
  newBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 4 },
  newText: { fontSize: fontSize.xs, fontWeight: '700' },
  hint: { fontSize: fontSize.sm, lineHeight: 20 },
  mono: { fontFamily: 'Menlo', fontSize: fontSize.xs },
  metricRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md },
  metricName: { fontSize: fontSize.md, fontWeight: '600' },
  metricExpr: { marginTop: 2 },
  fmt: { fontSize: fontSize.xs, fontWeight: '600' },
  err: { fontSize: fontSize.sm },
});
