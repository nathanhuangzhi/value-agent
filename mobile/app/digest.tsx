/**
 * Full "Today's Digest" screen at `/digest`. Reached by tapping the
 * DigestBanner on the home screen. Shows:
 *   - Header with date + industries + ticker count
 *   - LLM-generated "Stories of the Day" prose
 *   - Tappable list of every ticker in today's batch (same TickerRow
 *     component the industry-detail screen uses, so the row layout is
 *     consistent across both contexts)
 */
import { useEffect } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useNavigation } from 'expo-router';

import { useLatestDigest } from '@/api/hooks';
import { TickerRow } from '@/components/TickerRow';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useColors, fontSize, spacing } from '@/theme/colors';


export default function DigestScreen() {
  const c = useColors();
  const navigation = useNavigation();
  const device = useDeviceClass();
  const digest = useLatestDigest();

  useEffect(() => {
    // Skip on iPad-landscape: the screen renders inside SplitLayout's
    // Slot (no Stack header to write into).
    if (digest.data && device !== 'tablet-landscape') {
      navigation.setOptions({ title: "Today's Digest" });
    }
  }, [digest.data, navigation, device]);

  if (digest.error && !digest.data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={{ color: c.negative }}>{digest.error}</Text>
      </View>
    );
  }

  if (!digest.data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <ActivityIndicator color={c.brand} />
      </View>
    );
  }

  const data = digest.data;
  const industriesLabel = data.industries.join(', ') || 'Mixed';

  return (
    <FlatList
      style={{ backgroundColor: c.background }}
      data={data.tickers}
      keyExtractor={(t) => t.ticker}
      renderItem={({ item }) => <TickerRow row={item} />}
      refreshControl={
        <RefreshControl refreshing={digest.loading} onRefresh={digest.refresh} tintColor={c.brand} />
      }
      ListHeaderComponent={
        <View style={styles.header}>
          <Text style={[styles.subheading, { color: c.textMuted }]}>
            {data.date} · {industriesLabel} · {data.ticker_count} tickers
          </Text>

          {data.summary_md ? (
            <View style={styles.storiesBlock}>
              <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>
                STORIES OF THE DAY
              </Text>
              <Text style={[styles.summary, { color: c.textPrimary }]}>
                {data.summary_md.replace(/[*_`]+/g, '').trim()}
              </Text>
            </View>
          ) : (
            <View style={styles.storiesBlock}>
              <Text style={[styles.note, { color: c.textMuted }]}>
                No LLM summary yet — run{' '}
                <Text style={{ fontWeight: '600' }}>
                  python -m scripts.daily_digest --dry-run
                </Text>{' '}
                to generate one.
              </Text>
            </View>
          )}

          <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand, marginTop: spacing.xl }]}>
            ALL COMPANIES
          </Text>
        </View>
      }
    />
  );
}


const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
  },
  subheading: {
    fontSize: fontSize.sm,
    letterSpacing: 0.3,
  },
  storiesBlock: {
    marginTop: spacing.lg,
  },
  eyebrow: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 2,
    borderBottomWidth: 2,
    paddingBottom: 4,
    marginBottom: spacing.md,
  },
  summary: {
    fontSize: fontSize.md,
    lineHeight: 22,
  },
  note: {
    fontSize: fontSize.sm,
    fontStyle: 'italic',
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
});
