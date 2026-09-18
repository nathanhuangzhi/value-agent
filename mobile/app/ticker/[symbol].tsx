/**
 * Ticker detail screen: header, KPI grid, charts, the historical table
 * (with a sticky period header while it's on screen) and the inline AI
 * chat. Heavy children are deferred via InteractionManager so the page
 * appears before the charts and table are built.
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
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useNavigation } from 'expo-router';

import {
  useTickerDetail,
  usePriceHistory,
} from '@/api/hooks';
import { BusinessOverview } from '@/components/BusinessOverview';
import { ScrollToBottomButton } from '@/components/ScrollToBottomButton';
import { TickerChat } from '@/components/TickerChat';
import { SHOW_LLM_ANALYSIS } from '@/config';
import {
  HISTORICAL_TABLE_HEADER_HEIGHT,
  HistoricalTable,
  HistoricalTablePeriodHeader,
  computeHistoricalTableColumns,
} from '@/components/HistoricalTable';
import { KPIGrid } from '@/components/KPIGrid';
import { MyMetrics } from '@/components/MyMetrics';
import { Section } from '@/components/Section';
import { StatusBadge } from '@/components/StatusBadge';
import { ValuationGrid } from '@/components/ValuationGrid';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useLastViewed } from '@/hooks/useLastViewed';
import { useSaved } from '@/hooks/useSaved';
import { useColors, fontSize, spacing, radii } from '@/theme/colors';
import { formatDate, formatMoney } from '@/utils/format';

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
  // "Jump to bottom" while a chat is going on down there and the reader is scrolled up.
  const pageScrollRef = useRef<ScrollView>(null);
  const [chatActive, setChatActive] = useState(false);
  const [farFromBottom, setFarFromBottom] = useState(false);
  const tableColumns = useMemo(
    () =>
      ticker.data
        ? computeHistoricalTableColumns(ticker.data.annual, ticker.data.quarterly)
        : { columns: [], dividerIdx: 0 },
    [ticker.data],
  );

  const onPageScroll = useCallback(
    (e: { nativeEvent: { contentOffset: { y: number }; contentSize: { height: number }; layoutMeasurement: { height: number } } }) => {
      if (!isCenter) return;
      const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
      const y = contentOffset.y;
      const far = contentSize.height - layoutMeasurement.height - y > 400;
      setFarFromBottom((prev) => (prev === far ? prev : far));
      const top = tableTopRef.current;
      const h = tableHeightRef.current;
      if (top == null || h == null) return;
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

  const [showNative, setShowNative] = useState(false);

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
  // Non-USD filer: the API serves USD; the chip flips the statement tables
  // back to the reporting currency (multiplying by the baked daily rate).
  const fxMeta = data.currency && data.currency.per_usd ? data.currency : null;
  const fxFactor = fxMeta && showNative ? fxMeta.per_usd! : 1;
  const currencyLabel = fxMeta && showNative ? fxMeta.code : 'USD';

  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        ref={pageScrollRef}
        style={{ backgroundColor: c.background }}
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
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
          <SaveButton symbol={data.ticker} />
        </View>
        {fxMeta ? (
          <View style={styles.fxRow}>
            <Pressable
              onPress={() => setShowNative((v) => !v)}
              style={[styles.fxChip, { borderColor: c.brand, backgroundColor: showNative ? c.brand : 'transparent' }]}
              hitSlop={6}
            >
              <Text style={[styles.fxChipText, { color: showNative ? '#fff' : c.brand }]}>
                {showNative ? `${fxMeta.code} → show USD` : `USD → show ${fxMeta.code}`}
              </Text>
            </Pressable>
            <Text style={[styles.metaSmall, { color: c.textMuted, flex: 1 }]} numberOfLines={2}>
              Reports in {fxMeta.code} · {fxMeta.per_usd!.toFixed(4)} {fxMeta.code}/USD as of {fxMeta.as_of}
            </Text>
          </View>
        ) : null}

        <Section title="Business Overview">
          <BusinessOverview
            classification={data.classification}
            meta={data.classification_meta}
          />
        </Section>

        <Section title="Snapshot">
          <KPIGrid snapshot={data.snapshot} />
          <MyMetrics ticker={data.ticker} />
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
                fxFactor={fxFactor}
                currencyLabel={currencyLabel}
              />
            ) : (
              <View style={styles.chartLoading}>
                <ActivityIndicator color={c.brand} />
              </View>
            )}
          </Section>
        </View>

        {SHOW_LLM_ANALYSIS && (
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
        )}

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

        <TickerChat ticker={data.ticker} onActiveChange={setChatActive} />

        <View style={[styles.footer, { borderTopColor: c.border }]}>
          <Text style={[styles.disclaimer, { color: c.textMuted }]}>
            For research and educational purposes only. Not investment advice.
          </Text>
          <Text style={[styles.metaSmall, { color: c.textMuted }]}>
            Analyzed {formatDate(data.analyzed_date)}
            {SHOW_LLM_ANALYSIS ? ` · ${data.narrative.model || 'unknown model'}` : ''}
          </Text>
        </View>
      </ScrollView>

      <ScrollToBottomButton
        visible={isCenter && chatActive && farFromBottom}
        onPress={() => pageScrollRef.current?.scrollToEnd({ animated: true })}
      />

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

/** Bookmark toggle in the page header — adds/removes this company from
 * the Saved tab. Lives in the page (not the Stack header) so it also shows
 * on iPad-landscape, which renders without a Stack header. */
function SaveButton({ symbol }: { symbol: string }) {
  const c = useColors();
  const { isSaved, toggle } = useSaved();
  const saved = isSaved(symbol);
  return (
    <Pressable
      onPress={() => toggle(symbol)}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel={saved ? 'Remove from Saved' : 'Save company'}
      style={styles.saveBtn}
    >
      <Ionicons name={saved ? 'bookmark' : 'bookmark-outline'} size={24} color={saved ? c.brand : c.textMuted} />
    </Pressable>
  );
}

// ===========================================================================
// TickerScreen — one company page. (A swipe-between-siblings carousel used
// to live here; it competed with the historical table's horizontal scroll
// and was removed on 2026-09-17 — `git show 4ac597dd:mobile/app/ticker/[symbol].tsx`.)
// ===========================================================================
export default function TickerScreen() {
  const navigation = useNavigation();
  const device = useDeviceClass();
  const { symbol: initialSymbol } = useLocalSearchParams<{ symbol: string }>();
  const symbol = (initialSymbol || '').toUpperCase();

  // Remember the company viewed last, so its industry screen highlights it on return.
  const { setLastCompany } = useLastViewed();
  useEffect(() => {
    if (symbol) setLastCompany(symbol);
  }, [symbol, setLastCompany]);

  // Nav title. Skip on iPad-landscape (the SplitLayout renders without a Stack header).
  useEffect(() => {
    if (device !== 'tablet-landscape') {
      navigation.setOptions({ title: symbol });
    }
  }, [symbol, navigation, device]);

  return <TickerPageContent symbol={symbol} isCenter />;
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
  saveBtn: { marginLeft: spacing.md, paddingTop: 2 },
  fxRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  fxChip: { borderWidth: 1, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 4 },
  fxChipText: { fontSize: fontSize.xs, fontWeight: '700' },
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
