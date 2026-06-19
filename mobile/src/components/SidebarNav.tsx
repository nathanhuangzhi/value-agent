/**
 * Master-pane navigation for iPad-landscape split view.
 *
 * Layout (top to bottom):
 *   - Section header "INDUSTRIES"
 *   - One row per industry; tapping toggles selection
 *   - When an industry is selected:
 *       - A second list expands below showing that industry's tickers
 *       - The currently-active ticker (from URL params) is highlighted
 *   - A "Today's batch" pill at the top linking to /digest
 *
 * State strategy:
 *   - Selected industry is local state (clicking expands its tickers)
 *   - Active ticker is read from the URL (via `useLocalSearchParams`) —
 *     no separate state, so back-button / external links stay in sync
 *
 * The sidebar never navigates the user "away" — it just updates which
 * ticker is shown in the right pane via `router.push`. The route change
 * re-renders the Slot in `SplitLayout`.
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useRouter, useSegments } from 'expo-router';

import {
  prefetchTickerDetail,
  useIndustries,
  useIndustryDetail,
  useRecentDigests,
} from '@/api/hooks';
import type { IndustrySummary, TickerRow } from '@/api/types';
import { useLastViewed } from '@/hooks/useLastViewed';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';


export function SidebarNav() {
  const c = useColors();
  const router = useRouter();
  const segments = useSegments();
  const digests = useRecentDigests();

  // Shared cached fetch — `useIndustries` is the same hook the home screen
  // uses, so both panes share one network round trip.
  const industriesResp = useIndustries();
  const industries = industriesResp.data?.industries ?? null;
  const error = industriesResp.error;

  // Highlight the industry opened last time (this sidebar stands in for the
  // home screen's industry list on iPad-landscape).
  const { lastIndustry } = useLastViewed();

  // Track which industry is expanded in the sidebar. Defaults to the
  // most-recently-analyzed one once the list loads.
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  useEffect(() => {
    if (selectedSlug == null && industries && industries.length > 0) {
      setSelectedSlug(industries[0].slug);
    }
  }, [industries, selectedSlug]);

  // Which ticker is currently shown in the right pane? Derived from the
  // current URL segments: `/ticker/QDEL` → "QDEL". Cast through
  // `readonly string[]` because expo-router's typed-routes feature
  // returns a tuple union whose length-1 variant doesn't allow [1] —
  // the generated router.d.ts that smooths this over is gitignored
  // and therefore absent in CI.
  const segs = segments as readonly string[];
  const isOnTicker = segs[0] === 'ticker';
  const activeTicker = isOnTicker && segs[1] ? segs[1].toUpperCase() : null;

  /**
   * Navigate to a ticker. If we're already on a ticker page we `replace`
   * instead of `push` — otherwise tapping through several tickers stacks
   * them in history (A → B → C) and Back walks back through each one
   * instead of returning to the industry/home that the user came from.
   */
  const goToTicker = (ticker: string) => {
    const target = `/ticker/${ticker}` as const;
    if (isOnTicker) {
      router.replace(target);
    } else {
      router.push(target);
    }
  };

  if (error && !industries) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={{ color: c.negative }}>{error}</Text>
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

  const todayDigest = digests.data?.digests?.[0];

  return (
    <View style={[styles.sidebar, { backgroundColor: c.surface, borderRightColor: c.border }]}>
      <View style={styles.brandHeader}>
        <Text style={[styles.brand, { color: c.brand }]}>Valueland</Text>
      </View>

      {todayDigest ? (
        <Pressable
          onPress={() => router.push('/digest')}
          style={({ pressed }) => [
            styles.digestPill,
            {
              backgroundColor: pressed ? c.border : c.background,
              borderColor: c.brand,
            },
          ]}
        >
          <Text style={[styles.digestEyebrow, { color: c.brand }]}>TODAY'S BATCH</Text>
          <Text style={[styles.digestHeadline, { color: c.textPrimary }]} numberOfLines={1}>
            {todayDigest.industries.join(', ') || 'Mixed'}
          </Text>
          <Text style={[styles.digestSub, { color: c.textMuted }]}>
            {todayDigest.date} · {todayDigest.ticker_count} tickers
          </Text>
        </Pressable>
      ) : null}

      <Text style={[styles.sectionHeader, { color: c.textMuted }]}>INDUSTRIES</Text>

      <FlatList
        data={industries}
        keyExtractor={(i) => i.slug}
        renderItem={({ item }) => (
          <IndustryRow
            industry={item}
            isSelected={selectedSlug === item.slug}
            isLastViewed={item.slug === lastIndustry}
            onPress={() => setSelectedSlug(item.slug === selectedSlug ? null : item.slug)}
            activeTicker={activeTicker}
            onTickerPress={goToTicker}
          />
        )}
        // Sticky industry header rows so the user always sees what
        // section their tickers are in even when scrolled.
        stickyHeaderIndices={[]}
      />
    </View>
  );
}


function IndustryRow({
  industry,
  isSelected,
  isLastViewed,
  onPress,
  activeTicker,
  onTickerPress,
}: {
  industry: IndustrySummary;
  isSelected: boolean;
  isLastViewed: boolean;
  onPress: () => void;
  activeTicker: string | null;
  onTickerPress: (ticker: string) => void;
}) {
  const c = useColors();

  return (
    <View>
      <Pressable
        onPress={onPress}
        style={({ pressed }) => [
          styles.industryRow,
          {
            backgroundColor: pressed
              ? c.border
              : isLastViewed
                ? c.statusOkBg
                : 'transparent',
            borderBottomColor: c.border,
            borderLeftColor: isLastViewed ? c.brand : 'transparent',
          },
        ]}
      >
        <Text
          style={[
            styles.industryName,
            { color: isSelected ? c.brand : c.textPrimary },
          ]}
          numberOfLines={1}
        >
          {industry.name}
        </Text>
        <Text style={[styles.industryCount, { color: c.textMuted }]}>
          {industry.ticker_count}
        </Text>
      </Pressable>

      {isSelected ? (
        <TickerSubList
          slug={industry.slug}
          activeTicker={activeTicker}
          onTickerPress={onTickerPress}
        />
      ) : null}
    </View>
  );
}


function TickerSubList({
  slug,
  activeTicker,
  onTickerPress,
}: {
  slug: string;
  activeTicker: string | null;
  onTickerPress: (ticker: string) => void;
}) {
  const c = useColors();
  const detail = useIndustryDetail(slug);

  // Warm the ticker-detail + price-history caches for every ticker
  // listed in this industry so taps render instantly. Staggered so we
  // don't fire 10+ requests simultaneously and overwhelm the backend's
  // SEC/yfinance blender. prefetchTickerDetail is idempotent / dedupes
  // in-flight requests, so re-running on every render is fine.
  useEffect(() => {
    if (!detail.data) return;
    const tickers = detail.data.tickers.map((t) => t.ticker);
    let cancelled = false;
    let i = 0;
    const tick = () => {
      if (cancelled) return;
      const batch = tickers.slice(i, i + 2);
      batch.forEach(prefetchTickerDetail);
      i += 2;
      if (i < tickers.length) setTimeout(tick, 200);
    };
    tick();
    return () => { cancelled = true; };
  }, [detail.data]);

  if (detail.loading) {
    return (
      <View style={styles.tickerSubListLoading}>
        <ActivityIndicator color={c.brand} size="small" />
      </View>
    );
  }
  if (!detail.data) {
    return null;
  }
  return (
    <View style={[styles.tickerSubList, { backgroundColor: c.background }]}>
      {detail.data.tickers.map((t: TickerRow) => {
        const isActive = activeTicker === t.ticker;
        return (
          <Pressable
            key={t.ticker}
            onPress={() => {
              // Belt-and-suspenders: warm the cache on press in case the
              // stagger above hasn't reached this ticker yet.
              prefetchTickerDetail(t.ticker);
              onTickerPress(t.ticker);
            }}
            style={({ pressed }) => [
              styles.tickerRow,
              {
                backgroundColor: isActive
                  ? c.statusOkBg
                  : pressed
                    ? c.border
                    : 'transparent',
              },
            ]}
          >
            <Text
              style={[
                styles.tickerSymbol,
                { color: isActive ? c.brand : c.textPrimary, fontWeight: isActive ? '700' : '600' },
              ]}
              numberOfLines={1}
            >
              {t.ticker}
            </Text>
            <Text
              style={[styles.tickerName, { color: c.textMuted }]}
              numberOfLines={1}
            >
              {t.name}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}


const styles = StyleSheet.create({
  sidebar: {
    width: 280,
    borderRightWidth: StyleSheet.hairlineWidth,
  },
  brandHeader: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
  },
  brand: {
    fontSize: fontSize.xl,
    fontWeight: '700',
  },
  digestPill: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    borderRadius: radii.md,
    borderLeftWidth: 3,
    padding: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  digestEyebrow: {
    fontSize: fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 1.5,
  },
  digestHeadline: {
    fontSize: fontSize.sm,
    fontWeight: '700',
    marginTop: 4,
  },
  digestSub: {
    fontSize: fontSize.xs,
    marginTop: 2,
  },
  sectionHeader: {
    fontSize: fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 1.5,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  industryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    // Constant left border (transparent unless last-viewed) — no layout shift.
    borderLeftWidth: 3,
  },
  industryName: {
    fontSize: fontSize.sm,
    fontWeight: '600',
    flex: 1,
  },
  industryCount: {
    fontSize: fontSize.xs,
    marginLeft: spacing.sm,
  },
  tickerSubList: {
    paddingVertical: spacing.xs,
  },
  tickerSubListLoading: {
    padding: spacing.md,
    alignItems: 'center',
  },
  tickerRow: {
    paddingHorizontal: spacing.lg + spacing.sm,
    paddingVertical: 6,
  },
  tickerSymbol: {
    fontSize: fontSize.xs + 1,
    letterSpacing: 0.5,
  },
  tickerName: {
    fontSize: fontSize.xs,
    marginTop: 1,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
});
