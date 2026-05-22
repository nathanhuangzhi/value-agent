import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useLocalSearchParams, useNavigation } from 'expo-router';

import { api, ApiError } from '@/api/client';
import type { IndustryDetailResponse } from '@/api/types';
import { TickerRow, TickerRowHeader } from '@/components/TickerRow';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useColors, fontSize, spacing } from '@/theme/colors';

export default function IndustryScreen() {
  const c = useColors();
  const navigation = useNavigation();
  const device = useDeviceClass();
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const [data, setData] = useState<IndustryDetailResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug) return;
    setError(null);
    try {
      const resp = await api.industryDetail(slug);
      setData(resp);
      // Skip on iPad-landscape: the screen renders inside SplitLayout's
      // Slot (no Stack header to write into).
      if (device !== 'tablet-landscape') {
        navigation.setOptions({ title: resp.industry });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [slug, navigation, device]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  if (error && !data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={{ color: c.negative }}>{error}</Text>
      </View>
    );
  }

  if (!data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <ActivityIndicator color={c.brand} />
      </View>
    );
  }

  // SectionList lets us pin the column header (renderSectionHeader) while
  // the "N tickers" subheading scrolls away with the list contents. The
  // FlatList equivalent (`stickyHeaderIndices` on a ListHeaderComponent)
  // is unreliable across iOS versions.
  return (
    <SectionList
      style={{ backgroundColor: c.background }}
      sections={[{ data: data.tickers, key: 'all' }]}
      keyExtractor={(t) => t.ticker}
      ListHeaderComponent={
        <View style={styles.header}>
          <Text style={[styles.subheading, { color: c.textMuted }]}>
            {data.ticker_count} {data.ticker_count === 1 ? 'ticker' : 'tickers'}
          </Text>
        </View>
      }
      renderSectionHeader={() => <TickerRowHeader />}
      stickySectionHeadersEnabled
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.brand} />
      }
      renderItem={({ item }) => <TickerRow row={item} />}
    />
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  subheading: { fontSize: fontSize.sm },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
});
