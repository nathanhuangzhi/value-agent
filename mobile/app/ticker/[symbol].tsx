/**
 * Ticker detail screen rendered as a horizontal carousel: previous,
 * current, next tickers in the industry are mounted side-by-side so a
 * left/right swipe slides between them in one continuous motion — the
 * next page is already in memory when the user starts swiping (Tinder /
 * Stories pattern).
 *
 * Only the 3 pages adjacent to the current index are mounted. Heavy
 * children inside each page (charts + historical table) are still
 * deferred via InteractionManager so the JS thread isn't blocked
 * during the slide.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Animated,
  InteractionManager,
  PanResponder,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useLocalSearchParams, useNavigation } from 'expo-router';

import {
  prefetchTickerDetail,
  useIndustryDetail,
  useTickerDetail,
  usePriceHistory,
} from '@/api/hooks';
import { BusinessOverview } from '@/components/BusinessOverview';
import {
  HISTORICAL_TABLE_HEADER_HEIGHT,
  HistoricalTable,
  HistoricalTablePeriodHeader,
  computeHistoricalTableColumns,
} from '@/components/HistoricalTable';
import { KPIGrid } from '@/components/KPIGrid';
import { Section } from '@/components/Section';
import { StatusBadge } from '@/components/StatusBadge';
import { ValuationGrid } from '@/components/ValuationGrid';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useLastViewed } from '@/hooks/useLastViewed';
import { useColors, fontSize, spacing, radii } from '@/theme/colors';
import { formatDate, formatMoney } from '@/utils/format';

function slugify(s: string | null | undefined): string {
  if (!s) return 'uncategorized';
  const out = s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return out || 'uncategorized';
}

function pickLatestSourceDate(sources: { published_date?: string | null }[] | undefined): string | null {
  if (!sources || sources.length === 0) return null;
  const dates = sources
    .map((s) => (s.published_date ? s.published_date.slice(0, 10) : null))
    .filter((d): d is string => !!d);
  if (dates.length === 0) return null;
  dates.sort();
  return dates[dates.length - 1];
}

// ===========================================================================
// TickerPageContent — one full ticker page. Manages its own data hooks
// and vertical scrolling. The carousel below mounts up to three of these
// instances side-by-side.
// ===========================================================================
function TickerPageContent({ symbol, isCenter }: { symbol: string; isCenter: boolean }) {
  const c = useColors();
  const device = useDeviceClass();
  const contentMaxWidth = device === 'tablet-landscape' ? 900
                        : device === 'tablet'           ? 760
                        : undefined;

  const ticker = useTickerDetail(symbol);
  const priceHistory = usePriceHistory(symbol);

  // Defer heavy children (charts + historical table) past the current
  // frame so neither the initial mount nor a sibling becoming the
  // center hitches the JS thread.
  const [heavyVisible, setHeavyVisible] = useState(false);
  useEffect(() => {
    const handle = InteractionManager.runAfterInteractions(() => {
      setHeavyVisible(true);
    });
    return () => handle.cancel();
  }, []);

  const tableScrollX = useRef(new Animated.Value(0)).current;
  const tableTopRef = useRef<number | null>(null);
  const tableHeightRef = useRef<number | null>(null);
  const [showStickyOverlay, setShowStickyOverlay] = useState(false);
  const tableColumns = useMemo(
    () =>
      ticker.data
        ? computeHistoricalTableColumns(ticker.data.annual, ticker.data.quarterly)
        : { columns: [], dividerIdx: 0 },
    [ticker.data],
  );

  const onPageScroll = useCallback(
    (e: { nativeEvent: { contentOffset: { y: number } } }) => {
      if (!isCenter) return;
      const top = tableTopRef.current;
      const h = tableHeightRef.current;
      if (top == null || h == null) return;
      const y = e.nativeEvent.contentOffset.y;
      const show = y > top && y < top + h - HISTORICAL_TABLE_HEADER_HEIGHT;
      setShowStickyOverlay((prev) => (prev === show ? prev : show));
    },
    [isCenter],
  );

  // Hide the sticky overlay when this page is not center (otherwise an
  // off-screen sibling's overlay would still be in the view tree at top:0).
  useEffect(() => {
    if (!isCenter && showStickyOverlay) setShowStickyOverlay(false);
  }, [isCenter, showStickyOverlay]);

  async function refreshAll() {
    await Promise.all([ticker.refresh(), priceHistory.refresh()]);
  }

  if (ticker.error && !ticker.data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={{ color: c.negative }}>{ticker.error}</Text>
      </View>
    );
  }

  if (!ticker.data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <ActivityIndicator color={c.brand} />
      </View>
    );
  }

  const data = ticker.data;
  const latestSourceDate = pickLatestSourceDate(data.narrative.sources);

  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        style={{ backgroundColor: c.background }}
        contentContainerStyle={[
          styles.scroll,
          contentMaxWidth ? { maxWidth: contentMaxWidth, alignSelf: 'center', width: '100%' } : null,
        ]}
        refreshControl={
          <RefreshControl
            refreshing={ticker.loading || priceHistory.loading}
            onRefresh={refreshAll}
            tintColor={c.brand}
          />
        }
        onScroll={onPageScroll}
        scrollEventThrottle={32}
      >
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={[styles.companyName, { color: c.textPrimary }]} numberOfLines={2}>
              {data.name}
            </Text>
            <Text style={[styles.meta, { color: c.textMuted }]}>
              {[
                data.ticker,
                data.exchange,
                data.sector && data.industry
                  ? `${data.sector} / ${data.industry}`
                  : data.sector || data.industry,
                data.country,
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </View>
          <View style={styles.headerRight}>
            <Text style={[styles.mcap, { color: c.textPrimary }]}>
              {formatMoney(data.snapshot.market_cap)}
            </Text>
            <Text style={[styles.metaSmall, { color: c.textMuted }]}>Market Cap</Text>
          </View>
        </View>

        <Section title="Business Overview">
          <BusinessOverview
            classification={data.classification}
            meta={data.classification_meta}
          />
        </Section>

        <Section title="Snapshot">
          <KPIGrid snapshot={data.snapshot} />
        </Section>

        <Section title="Stock Price & Valuation">
          {heavyVisible && priceHistory.data ? (
            <ValuationGrid
              annual={data.annual}
              quarterly={data.quarterly}
              priceHistory={priceHistory.data.data}
            />
          ) : (
            <View style={styles.chartLoading}>
              <ActivityIndicator color={c.brand} />
            </View>
          )}
        </Section>

        <View
          onLayout={(e) => {
            tableTopRef.current = e.nativeEvent.layout.y;
            tableHeightRef.current = e.nativeEvent.layout.height;
          }}
        >
          <Section title="Historical Data (annual + quarterly)">
            {heavyVisible ? (
              <HistoricalTable
                statements={data.annual}
                quarterly={data.quarterly}
                priceHistory={priceHistory.data?.data}
                externalScrollX={tableScrollX}
              />
            ) : (
              <View style={styles.chartLoading}>
                <ActivityIndicator color={c.brand} />
              </View>
            )}
          </Section>
        </View>

        <Section title="Investment Narrative">
          {latestSourceDate ? (
            <Text style={[styles.metaSmall, { color: c.textMuted, marginBottom: spacing.sm }]}>
              Most recent source: {latestSourceDate}
            </Text>
          ) : null}
          <Text style={[styles.body, { color: c.textPrimary }]}>
            {data.narrative.text || '(no narrative available)'}
          </Text>
        </Section>

        {(data.validation.status === 'warn' || data.validation.status === 'error') && (
          <View
            style={[
              styles.validationBanner,
              {
                backgroundColor:
                  data.validation.status === 'error' ? c.statusErrorBg : c.statusWarnBg,
                borderLeftColor:
                  data.validation.status === 'error' ? c.negative : c.warning,
              },
            ]}
          >
            <View style={styles.bannerHeader}>
              <StatusBadge status={data.validation.status} />
              <Text style={[styles.bannerTitle, { color: c.textPrimary }]}>
                Data quality {data.validation.status === 'error' ? 'errors' : 'warnings'}
              </Text>
            </View>
            {data.validation.issues
              .filter((i) => i.severity !== 'info')
              .slice(0, 3)
              .map((i, idx) => (
                <Text
                  key={idx}
                  style={[styles.bannerIssue, { color: c.textMuted }]}
                  numberOfLines={2}
                >
                  • {i.detail}
                </Text>
              ))}
          </View>
        )}

        <View style={[styles.footer, { borderTopColor: c.border }]}>
          <Text style={[styles.disclaimer, { color: c.textMuted }]}>
            For research and educational purposes only. Not investment advice.
          </Text>
          <Text style={[styles.metaSmall, { color: c.textMuted }]}>
            Analyzed {formatDate(data.analyzed_date)} · {data.narrative.model || 'unknown model'}
          </Text>
        </View>
      </ScrollView>

      {showStickyOverlay && (
        <View
          pointerEvents="none"
          style={[styles.stickyOverlay, { backgroundColor: c.background }]}
        >
          <HistoricalTablePeriodHeader
            columns={tableColumns.columns}
            dividerIdx={tableColumns.dividerIdx}
            scrollX={tableScrollX}
          />
        </View>
      )}
    </View>
  );
}

// Memoize: the carousel re-renders frequently as containerX animates;
// re-rendering a sibling page that hasn't changed is wasteful.
const TickerPage = TickerPageContent;

// ===========================================================================
// TickerScreen — carousel container.
// ===========================================================================
export default function TickerScreen() {
  const c = useColors();
  const navigation = useNavigation();
  const device = useDeviceClass();
  const { symbol: initialSymbol } = useLocalSearchParams<{ symbol: string }>();
  const initialSym = (initialSymbol || '').toUpperCase();

  // Pull the industry's ticker list so we can compute neighbours. Fetch
  // via the *first* ticker we have data for (the deep-link target);
  // once we know its industry, the list arrives and we lock in.
  const initialTicker = useTickerDetail(initialSym);
  const industrySlug = initialTicker.data
    ? slugify(initialTicker.data.industry)
    : undefined;
  const industryDetail = useIndustryDetail(industrySlug);
  const tickerList = useMemo(
    () => industryDetail.data?.tickers.map((t) => t.ticker) ?? [],
    [industryDetail.data],
  );

  // Centre index walks through the industry list as the user swipes.
  // Default to the index of the initial URL ticker once the list arrives,
  // or -1 if not found (single-ticker mode).
  const [centerIndex, setCenterIndex] = useState(-1);
  useEffect(() => {
    if (centerIndex !== -1 || tickerList.length === 0) return;
    const idx = tickerList.indexOf(initialSym);
    if (idx >= 0) setCenterIndex(idx);
  }, [tickerList, initialSym, centerIndex]);

  const centerSymbol = centerIndex >= 0 ? tickerList[centerIndex] : initialSym;

  // Remember the currently-centred ticker as the company viewed last, so its
  // industry screen highlights it on return. Tracks swipes between siblings.
  const { setLastCompany } = useLastViewed();
  useEffect(() => {
    if (centerSymbol) setLastCompany(centerSymbol);
  }, [centerSymbol, setLastCompany]);

  // Nav title tracks the currently-centred ticker. Skip on iPad-landscape
  // (the SplitLayout renders without a Stack header).
  useEffect(() => {
    if (device !== 'tablet-landscape') {
      navigation.setOptions({ title: centerSymbol });
    }
  }, [centerSymbol, navigation, device]);

  // Prefetch the symbols around the centre so they're cache-warm when the
  // user swipes into them.
  useEffect(() => {
    if (centerIndex < 0) return;
    [centerIndex - 1, centerIndex + 1].forEach((i) => {
      if (i >= 0 && i < tickerList.length) prefetchTickerDetail(tickerList[i]);
    });
  }, [centerIndex, tickerList]);

  // Carousel translateX. Resting value = -centerIndex * screenWidth so
  // the centre page sits at screen x = 0. During pan we superimpose the
  // gesture dx as an Animated offset.
  const { width: screenWidth } = useWindowDimensions();
  const containerX = useRef(new Animated.Value(0)).current;
  // Sync resting position to centerIndex changes. Using setValue
  // (not animate) because the swipe-completion handler has already
  // animated to this position before swapping centerIndex.
  useEffect(() => {
    if (centerIndex < 0) return;
    containerX.setValue(-centerIndex * screenWidth);
  }, [centerIndex, screenWidth, containerX]);

  const centerIndexRef = useRef(centerIndex);
  centerIndexRef.current = centerIndex;
  const tickerListLengthRef = useRef(tickerList.length);
  tickerListLengthRef.current = tickerList.length;

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, g) =>
          Math.abs(g.dx) > Math.abs(g.dy) * 2 && Math.abs(g.dx) > 10,
        onPanResponderGrant: () => {
          const base = -centerIndexRef.current * screenWidth;
          containerX.setOffset(base);
          containerX.setValue(0);
        },
        onPanResponderMove: (_, g) => {
          containerX.setValue(g.dx);
        },
        onPanResponderRelease: (_, g) => {
          containerX.flattenOffset();
          const SWIPE_DISTANCE = 80;
          const SWIPE_VELOCITY = 0.35;
          const left = g.dx < -SWIPE_DISTANCE || g.vx < -SWIPE_VELOCITY;
          const right = g.dx > SWIPE_DISTANCE || g.vx > SWIPE_VELOCITY;
          const idx = centerIndexRef.current;
          const len = tickerListLengthRef.current;
          // Left swipe → next (higher index); right swipe → previous.
          let targetIdx = idx;
          if (left && idx < len - 1) targetIdx = idx + 1;
          else if (right && idx > 0) targetIdx = idx - 1;

          if (targetIdx !== idx) {
            Animated.timing(containerX, {
              toValue: -targetIdx * screenWidth,
              duration: 200,
              useNativeDriver: true,
            }).start(() => {
              // containerX is already at -targetIdx * screenWidth, which
              // is the resting position for the new centre. Updating
              // centerIndex does NOT cause a visual jump because the
              // useEffect above setValue's the same value we just
              // animated to.
              setCenterIndex(targetIdx);
            });
          } else {
            Animated.spring(containerX, {
              toValue: -idx * screenWidth,
              useNativeDriver: true,
              bounciness: 6,
            }).start();
          }
        },
        onPanResponderTerminate: () => {
          containerX.flattenOffset();
          Animated.spring(containerX, {
            toValue: -centerIndexRef.current * screenWidth,
            useNativeDriver: true,
            bounciness: 6,
          }).start();
        },
      }),
    [screenWidth, containerX],
  );

  if (initialTicker.error && !initialTicker.data) {
    return (
      <View style={[styles.center, { backgroundColor: c.background }]}>
        <Text style={{ color: c.negative }}>{initialTicker.error}</Text>
      </View>
    );
  }

  // Once we know the industry's ticker list, render the carousel.
  // While the list is still loading, render the single page so the
  // user isn't waiting on an industry round-trip to see anything.
  if (tickerList.length === 0 || centerIndex < 0) {
    return (
      <View style={{ flex: 1, backgroundColor: c.background }}>
        <TickerPage symbol={initialSym} isCenter />
      </View>
    );
  }

  return (
    <View
      style={{ flex: 1, backgroundColor: c.background }}
      {...panResponder.panHandlers}
    >
      <Animated.View
        style={{
          flex: 1,
          flexDirection: 'row',
          width: tickerList.length * screenWidth,
          transform: [{ translateX: containerX }],
        }}
      >
        {tickerList.map((sym, i) => {
          // Only mount the centre and its immediate neighbours; everything
          // else stays as a fixed-width spacer so the layout coordinates
          // stay correct.
          const distance = Math.abs(i - centerIndex);
          return (
            <View key={sym} style={{ width: screenWidth }}>
              {distance <= 1 ? (
                <TickerPage symbol={sym} isCenter={i === centerIndex} />
              ) : null}
            </View>
          );
        })}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingBottom: spacing.xxl },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  headerRight: { alignItems: 'flex-end', marginLeft: spacing.md },
  companyName: { fontSize: fontSize.xl, fontWeight: '700', lineHeight: 28 },
  meta: { fontSize: fontSize.sm, marginTop: 4 },
  metaSmall: { fontSize: fontSize.xs, letterSpacing: 0.3 },
  mcap: { fontSize: fontSize.lg, fontWeight: '700', fontVariant: ['tabular-nums'] },
  validationBanner: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.lg,
    borderLeftWidth: 4,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  bannerHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  bannerTitle: { fontSize: fontSize.sm, fontWeight: '600' },
  bannerIssue: { fontSize: fontSize.xs + 1, marginTop: spacing.sm, lineHeight: 18 },
  body: { fontSize: fontSize.md, lineHeight: 22 },
  footer: {
    marginTop: spacing.xxl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  disclaimer: {
    fontSize: fontSize.xs,
    fontStyle: 'italic',
    marginBottom: 4,
  },
  chartLoading: {
    height: 200,
    alignItems: 'center',
    justifyContent: 'center',
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  stickyOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
  },
});
