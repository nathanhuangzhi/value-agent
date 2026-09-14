/**
 * Saved tab — the user's own watchlist.
 *
 *   ┌ search bar ───────────────────────────────┐  filters the whole
 *   │ results (while typing): ticker · name · + │  NYSE+Nasdaq universe
 *   ├ SAVED ────────────────────────────────────┤  (/api/search.json)
 *   │ TickerRow … exactly like an industry page │
 *   └───────────────────────────────────────────┘
 *
 * Saved companies that have been analyzed render as the same `TickerRow`
 * the industry pages use (1Y sparkline + KPIs), sourced from their
 * industry's `/api/industries/<slug>.json`; companies that haven't been
 * through a batch yet render as a plain identity row tagged "Not analyzed
 * yet". Long-press any saved row to remove it.
 */
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { fetchIndustry, useSearchIndex } from '@/api/hooks';
import type { SearchCompany, TickerRow as TickerRowData } from '@/api/types';
import { TickerRow, TickerRowHeader } from '@/components/TickerRow';
import { useLastViewed } from '@/hooks/useLastViewed';
import { useSaved } from '@/hooks/useSaved';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';
import { formatMoney, slugify } from '@/utils/format';

const MAX_RESULTS = 40;

/** Ticker-prefix matches first (the usual intent), then name substrings. */
function search(index: SearchCompany[], query: string): SearchCompany[] {
  const q = query.trim().toUpperCase();
  if (!q) return [];
  const byTicker: SearchCompany[] = [];
  const byName: SearchCompany[] = [];
  const ql = q.toLowerCase();
  for (const c of index) {
    if (c.ticker.startsWith(q)) byTicker.push(c);
    else if (c.name.toLowerCase().includes(ql)) byName.push(c);
    if (byTicker.length >= MAX_RESULTS) break;
  }
  return [...byTicker, ...byName].slice(0, MAX_RESULTS);
}

/**
 * KPI rows for the saved *analyzed* tickers, pulled from each industry's
 * detail payload (one cached fetch per distinct industry).
 */
function useSavedKpiRows(saved: SearchCompany[]): Map<string, TickerRowData> {
  const [rows, setRows] = useState<Map<string, TickerRowData>>(new Map());
  const slugs = useMemo(
    () => Array.from(new Set(saved.filter((c) => c.analyzed).map((c) => slugify(c.industry)))),
    [saved],
  );
  const slugKey = slugs.join('|');
  useEffect(() => {
    let cancelled = false;
    if (slugs.length === 0) {
      setRows(new Map());
      return;
    }
    Promise.all(slugs.map((s) => fetchIndustry(s).catch(() => null))).then((payloads) => {
      if (cancelled) return;
      const next = new Map<string, TickerRowData>();
      for (const p of payloads) {
        for (const r of p?.tickers ?? []) next.set(r.ticker, r);
      }
      setRows(next);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slugKey]);
  return rows;
}

export default function SavedScreen() {
  const c = useColors();
  const index = useSearchIndex();
  const { tickers: savedTickers, ready, isSaved, toggle, remove } = useSaved();
  const { lastCompany } = useLastViewed();
  const [query, setQuery] = useState('');

  const byTicker = useMemo(() => {
    const m = new Map<string, SearchCompany>();
    for (const c of index.data ?? []) m.set(c.ticker, c);
    return m;
  }, [index.data]);

  const savedCompanies = useMemo(
    () =>
      savedTickers.map(
        (t) =>
          byTicker.get(t) ?? {
            ticker: t, name: t, industry: '', market_cap: null, analyzed: false,
          },
      ),
    [savedTickers, byTicker],
  );
  const kpiRows = useSavedKpiRows(savedCompanies);
  const results = useMemo(() => search(index.data ?? [], query), [index.data, query]);
  const searching = query.trim().length > 0;

  const confirmRemove = (ticker: string) =>
    Alert.alert(`Remove ${ticker}?`, 'It will disappear from your Saved list.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => remove(ticker) },
    ]);

  const sections = searching
    ? [{ key: 'results', title: `RESULTS · ${results.length}`, data: results }]
    : [{ key: 'saved', title: `SAVED · ${savedCompanies.length}`, data: savedCompanies }];

  return (
    <SectionList
      style={{ backgroundColor: c.background }}
      contentContainerStyle={styles.list}
      sections={sections}
      keyExtractor={(item) => item.ticker}
      keyboardShouldPersistTaps="handled"
      stickySectionHeadersEnabled
      ListHeaderComponent={
        <View style={[styles.searchWrap, { backgroundColor: c.background }]}>
          <View style={[styles.searchBox, { backgroundColor: c.surface, borderColor: c.border }]}>
            <Ionicons name="search" size={16} color={c.textMuted} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search any NYSE / Nasdaq company"
              placeholderTextColor={c.textMuted}
              autoCapitalize="characters"
              autoCorrect={false}
              clearButtonMode="while-editing"
              returnKeyType="search"
              style={[styles.searchInput, { color: c.textPrimary }]}
            />
            {query ? (
              <Pressable onPress={() => setQuery('')} hitSlop={8}>
                <Ionicons name="close-circle" size={16} color={c.textMuted} />
              </Pressable>
            ) : null}
          </View>
          {index.error && !index.data ? (
            <Text style={[styles.note, { color: c.negative }]}>
              Search index unavailable: {index.error}
            </Text>
          ) : index.loading && !index.data ? (
            <View style={styles.inlineLoading}>
              <ActivityIndicator color={c.brand} size="small" />
              <Text style={[styles.note, { color: c.textMuted }]}>Loading company list…</Text>
            </View>
          ) : null}
        </View>
      }
      renderSectionHeader={({ section }) => (
        <View style={{ backgroundColor: c.background }}>
          <View style={styles.eyebrowWrap}>
            <Text style={[styles.eyebrow, { color: c.brand, borderBottomColor: c.brand }]}>
              {section.title}
            </Text>
          </View>
          {!searching && savedCompanies.some((s) => s.analyzed) ? (
            <TickerRowHeader showChart />
          ) : null}
        </View>
      )}
      renderItem={({ item, index: i }) => {
        if (searching) {
          return (
            <SearchResultRow
              company={item}
              saved={isSaved(item.ticker)}
              onToggle={() => toggle(item.ticker)}
            />
          );
        }
        const kpi = item.analyzed ? kpiRows.get(item.ticker) : undefined;
        if (kpi) {
          return (
            <TickerRow
              row={kpi}
              highlighted={item.ticker === lastCompany}
              showChart
              chartDelay={i * 80}
              onLongPress={() => confirmRemove(item.ticker)}
            />
          );
        }
        return (
          <PlainSavedRow
            company={item}
            pending={item.analyzed}
            onLongPress={() => confirmRemove(item.ticker)}
          />
        );
      }}
      ListEmptyComponent={
        <View style={styles.empty}>
          <Text style={[styles.emptyTitle, { color: c.textPrimary }]}>
            {searching ? 'No matches' : ready ? 'Nothing saved yet' : ''}
          </Text>
          {!searching && ready ? (
            <Text style={[styles.note, { color: c.textMuted }]}>
              Search above and tap + to add a company, or tap the bookmark on any company page.
            </Text>
          ) : null}
        </View>
      }
    />
  );
}

/** A search hit: identity + market cap, with a save toggle on the right. */
function SearchResultRow({
  company,
  saved,
  onToggle,
}: {
  company: SearchCompany;
  saved: boolean;
  onToggle: () => void;
}) {
  const c = useColors();
  return (
    <View style={[styles.plainRow, { borderBottomColor: c.border }]}>
      <View style={styles.plainLeft}>
        <View style={styles.tickerLine}>
          <Text style={[styles.ticker, { color: c.textPrimary }]}>{company.ticker}</Text>
          {company.analyzed ? (
            <View style={[styles.tag, { backgroundColor: c.statusOkBg }]}>
              <Text style={[styles.tagText, { color: c.brand }]}>ANALYZED</Text>
            </View>
          ) : null}
        </View>
        <Text style={[styles.name, { color: c.textMuted }]} numberOfLines={1}>
          {company.name}
          {company.industry ? ` · ${company.industry}` : ''}
        </Text>
      </View>
      <Text style={[styles.mcap, { color: c.textPrimary }]}>{formatMoney(company.market_cap)}</Text>
      <Pressable onPress={onToggle} hitSlop={10} style={styles.toggle}>
        <Ionicons
          name={saved ? 'bookmark' : 'add-circle-outline'}
          size={24}
          color={saved ? c.brand : c.textMuted}
        />
      </Pressable>
    </View>
  );
}

/** A saved company with no industry-page row (never analyzed, or its KPI
 * payload is still loading). */
function PlainSavedRow({
  company,
  pending,
  onLongPress,
}: {
  company: SearchCompany;
  pending: boolean;
  onLongPress: () => void;
}) {
  const c = useColors();
  return (
    <Pressable onLongPress={onLongPress} style={[styles.plainRow, { borderBottomColor: c.border }]}>
      <View style={styles.plainLeft}>
        <Text style={[styles.ticker, { color: c.textPrimary }]}>{company.ticker}</Text>
        <Text style={[styles.name, { color: c.textMuted }]} numberOfLines={1}>
          {company.name}
          {company.industry ? ` · ${company.industry}` : ''}
        </Text>
      </View>
      <View style={styles.plainRight}>
        <Text style={[styles.mcap, { color: c.textPrimary }]}>{formatMoney(company.market_cap)}</Text>
        {pending ? (
          <ActivityIndicator size="small" color={c.textMuted} />
        ) : (
          <Text style={[styles.notAnalyzed, { color: c.textMuted }]}>Not analyzed yet</Text>
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { paddingBottom: spacing.xxl },
  searchWrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  searchInput: { flex: 1, fontSize: fontSize.md, paddingVertical: 4 },
  inlineLoading: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.sm },
  note: { fontSize: fontSize.sm, marginTop: spacing.sm, lineHeight: 20 },
  eyebrowWrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm },
  eyebrow: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 1.5,
    borderBottomWidth: 2,
    paddingBottom: 4,
    alignSelf: 'flex-start',
  },
  plainRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: spacing.md,
  },
  plainLeft: { flex: 1, minWidth: 0 },
  plainRight: { alignItems: 'flex-end', gap: 2 },
  tickerLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  ticker: { fontSize: fontSize.md, fontWeight: '700' },
  name: { fontSize: fontSize.xs, marginTop: 2 },
  mcap: { fontSize: fontSize.sm, fontVariant: ['tabular-nums'] },
  notAnalyzed: { fontSize: fontSize.xs - 1, letterSpacing: 0.3 },
  tag: { borderRadius: radii.sm, paddingHorizontal: 5, paddingVertical: 1 },
  tagText: { fontSize: 9, fontWeight: '700', letterSpacing: 0.8 },
  toggle: { paddingLeft: spacing.xs },
  empty: { paddingHorizontal: spacing.lg, paddingVertical: spacing.xl },
  emptyTitle: { fontSize: fontSize.md, fontWeight: '600' },
});
