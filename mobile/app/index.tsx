import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';

import { api, ApiError } from '@/api/client';
import { useLatestDigest } from '@/api/hooks';
import type { IndustrySummary } from '@/api/types';
import { DigestBanner } from '@/components/DigestBanner';
import { useColors, fontSize, spacing, radii } from '@/theme/colors';

export default function HomeScreen() {
  const c = useColors();
  const router = useRouter();
  const [industries, setIndustries] = useState<IndustrySummary[] | null>(null);
  const [totalTickers, setTotalTickers] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const digest = useLatestDigest();

  const load = useCallback(async () => {
    setError(null);
    try {
      const resp = await api.listIndustries();
      setIndustries(resp.industries);
      setTotalTickers(resp.total_tickers);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([load(), digest.refresh()]);
    setRefreshing(false);
  }, [load, digest]);

  if (error && !industries) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={[styles.errorTitle, { color: c.negative }]}>Could not reach the API.</Text>
        <Text style={[styles.errorDetail, { color: c.textMuted }]}>{error}</Text>
        <Pressable
          onPress={load}
          style={[styles.retryBtn, { borderColor: c.brand }]}
        >
          <Text style={[styles.retryLabel, { color: c.brand }]}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (!industries) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <ActivityIndicator color={c.brand} />
      </View>
    );
  }

  return (
    <FlatList
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.list}
      data={industries}
      keyExtractor={(i) => i.slug}
      ListHeaderComponent={
        <>
          <View style={styles.header}>
            <Text style={[styles.heading, { color: c.textPrimary }]}>
              Equity Research
            </Text>
            <Text style={[styles.subheading, { color: c.textMuted }]}>
              {industries.length} {industries.length === 1 ? 'industry' : 'industries'} · {totalTickers} tickers
            </Text>
          </View>
          {/* Digest banner: hidden until the digest hook resolves; null
              when there's no data (no daily-scan log entries yet). */}
          {digest.data ? <DigestBanner digest={digest.data} /> : null}
          <View style={styles.industriesEyebrow}>
            <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>
              INDUSTRIES
            </Text>
          </View>
        </>
      }
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.brand} />
      }
      renderItem={({ item }) => (
        <Pressable
          onPress={() => router.push(`/industry/${item.slug}`)}
          style={({ pressed }) => [
            styles.industryRow,
            {
              backgroundColor: pressed ? c.surface : c.background,
              borderBottomColor: c.border,
            },
          ]}
        >
          <View style={{ flex: 1 }}>
            <Text style={[styles.industryName, { color: c.textPrimary }]}>{item.name}</Text>
            <Text style={[styles.industryMeta, { color: c.textMuted }]}>
              Last analyzed {item.latest_analyzed}
            </Text>
          </View>
          <View style={styles.countWrap}>
            <Text style={[styles.count, { color: c.brand }]}>{item.ticker_count}</Text>
            <Text style={[styles.countLabel, { color: c.textMuted }]}>tickers</Text>
          </View>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: { paddingBottom: spacing.xxl },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  heading: { fontSize: fontSize.xxl, fontWeight: '700' },
  subheading: { fontSize: fontSize.sm, marginTop: 4 },
  industriesEyebrow: {
    paddingHorizontal: spacing.lg,
    marginTop: spacing.lg,
    marginBottom: spacing.xs,
  },
  eyebrow: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 2,
    borderBottomWidth: 2,
    paddingBottom: 4,
  },
  industryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  industryName: { fontSize: fontSize.md, fontWeight: '600' },
  industryMeta: { fontSize: fontSize.xs, marginTop: 4, letterSpacing: 0.5 },
  countWrap: { alignItems: 'flex-end', marginLeft: spacing.md },
  count: { fontSize: fontSize.xl, fontWeight: '700', fontVariant: ['tabular-nums'] },
  countLabel: { fontSize: fontSize.xs - 1, letterSpacing: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  errorTitle: { fontSize: fontSize.md, fontWeight: '700', marginBottom: spacing.sm },
  errorDetail: { fontSize: fontSize.sm, textAlign: 'center' },
  retryBtn: {
    marginTop: spacing.lg,
    borderWidth: 1,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radii.md,
  },
  retryLabel: { fontSize: fontSize.sm, fontWeight: '600' },
});
