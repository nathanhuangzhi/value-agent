import { useEffect } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useLocalSearchParams, useNavigation } from 'expo-router';

import { useTickerDetail, usePriceHistory } from '@/api/hooks';
import { BusinessOverview } from '@/components/BusinessOverview';
import { HistoricalTable } from '@/components/HistoricalTable';
import { KPIGrid } from '@/components/KPIGrid';
import { Section } from '@/components/Section';
import { StatusBadge } from '@/components/StatusBadge';
import { ValuationGrid } from '@/components/ValuationGrid';
import { useDeviceClass } from '@/hooks/useDeviceClass';
import { useColors, fontSize, spacing, radii } from '@/theme/colors';
import { formatDate, formatMoney } from '@/utils/format';

export default function TickerScreen() {
  const c = useColors();
  const navigation = useNavigation();
  const device = useDeviceClass();
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  // On iPad-landscape the screen is rendered inside the SplitLayout's
  // right pane (no Stack header), but it still benefits from being
  // centered with a comfortable max-width so the eye doesn't scan
  // across 800+ pt of statement text.
  const contentMaxWidth = device === 'tablet-landscape' ? 900
                        : device === 'tablet'           ? 760
                        : undefined;

  const ticker = useTickerDetail(symbol);
  const priceHistory = usePriceHistory(symbol);

  // Update the nav title once the ticker payload arrives. Skipped on
  // iPad-landscape where the screen renders inside SplitLayout's Slot
  // (no Stack header to write into).
  useEffect(() => {
    if (ticker.data && device !== 'tablet-landscape') {
      navigation.setOptions({ title: ticker.data.ticker });
    }
  }, [ticker.data, navigation, device]);

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
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentContainerStyle={[
        styles.scroll,
        // Center the content with a max-width on iPad so a wide screen
        // doesn't sprawl statement text across 1000+ pt of horizontal space.
        contentMaxWidth ? { maxWidth: contentMaxWidth, alignSelf: 'center', width: '100%' } : null,
      ]}
      refreshControl={
        <RefreshControl
          refreshing={ticker.loading || priceHistory.loading}
          onRefresh={refreshAll}
          tintColor={c.brand}
        />
      }
    >
      {/* Header */}
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

      {/* Business overview — matches the web's bullet-list shape: a
          "What it does" summary plus 9 categorical attributes from the
          Stage 2 classifier. Lives at the top because it's the
          "what is this company" framing the reader needs before any
          numbers make sense. */}
      <Section title="Business Overview">
        <BusinessOverview
          classification={data.classification}
          meta={data.classification_meta}
        />
      </Section>

      {/* Snapshot KPI grid */}
      <Section title="Snapshot">
        <KPIGrid snapshot={data.snapshot} />
      </Section>

      {/* 2×2 grid: stock price + static P/E + static P/S + P/B. Mirrors
          the web report's valuation panel. Each chart is interactive on
          tap — same data the historical-table "Valuation Multiples"
          rows are computed from, visualized over time. */}
      <Section title="Stock Price & Valuation">
        {priceHistory.data ? (
          <ValuationGrid
            annual={data.annual}
            quarterly={data.quarterly}
            priceHistory={priceHistory.data.data}
          />
        ) : priceHistory.loading ? (
          <View style={styles.chartLoading}>
            <ActivityIndicator color={c.brand} />
          </View>
        ) : (
          <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>
            {priceHistory.error ?? '(no price data)'}
          </Text>
        )}
      </Section>

      {/* Historical statements: annual + quarterly in one scroll,
          default-anchored to the most recent quarter on the right.
          Price history is passed in so the table can compute Static P/E,
          Static P/S, and P/B for each period (price × diluted shares ÷
          annual baseline). */}
      <Section title="Historical Data (annual + quarterly)">
        <HistoricalTable
          statements={data.annual}
          quarterly={data.quarterly}
          priceHistory={priceHistory.data?.data}
        />
      </Section>

      {/* Investment narrative */}
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

      {/* Validation banner — moved to the BOTTOM of the page. Same data
          quality info but framed as an end-of-report caveat rather than
          a top-of-page interruption. Only rendered on warn / error. */}
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

      {/* Footer — disclaimer (matches the web) + analyzed-date stamp. */}
      <View style={[styles.footer, { borderTopColor: c.border }]}>
        <Text style={[styles.disclaimer, { color: c.textMuted }]}>
          For research and educational purposes only. Not investment advice.
        </Text>
        <Text style={[styles.metaSmall, { color: c.textMuted }]}>
          Analyzed {formatDate(data.analyzed_date)} · {data.narrative.model || 'unknown model'}
        </Text>
      </View>
    </ScrollView>
  );
}

/**
 * Mirror the Python `_latest_source_date` helper: pick the latest
 * `published_date` from the source list. URL/snippet regex fallbacks
 * happen on the backend already (the renderer's `_parse_source_date`),
 * so by the time data reaches us the field is just an ISO string.
 */
function pickLatestSourceDate(sources: { published_date?: string | null }[] | undefined): string | null {
  if (!sources || sources.length === 0) return null;
  const dates = sources
    .map((s) => (s.published_date ? s.published_date.slice(0, 10) : null))
    .filter((d): d is string => !!d);
  if (dates.length === 0) return null;
  dates.sort();
  return dates[dates.length - 1];
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
});
