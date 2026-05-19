/**
 * Compact "daily batch" card for the home screen. The home screen renders
 * one of these per past daily-scan batch (newest first).
 *
 * Routing depends on `is_latest`:
 *   - Latest batch (today)   → opens `/digest` (full summary + ticker list)
 *   - Older batches          → opens `/industry/<slug>` (ticker list only —
 *                              older batches have no persisted LLM summary
 *                              to show, so the dedicated digest screen
 *                              would be empty)
 *
 * The latest banner shows the first sentence of the LLM summary as a
 * teaser. Older banners just show date · industry · ticker count.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import type { RecentDigest } from '@/api/types';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';


function firstSentence(md: string, max: number = 180): string {
  if (!md) return '';
  const stripped = md.replace(/[*_`]+/g, '').trim();
  const match = stripped.match(/^.+?[.!?](\s|$)/);
  const candidate = match ? match[0].trim() : stripped;
  if (candidate.length <= max) return candidate;
  return candidate.slice(0, max - 1).trimEnd() + '…';
}


export function DigestBanner({ digest }: { digest: RecentDigest }) {
  const c = useColors();
  const router = useRouter();
  if (!digest || !digest.ticker_count) return null;

  const teaser = firstSentence(digest.summary_md);
  const eyebrow = digest.is_latest ? "TODAY'S BATCH" : 'PAST BATCH';

  const goToDetail = () => {
    if (digest.is_latest) {
      router.push('/digest');
    } else if (digest.slug) {
      router.push(`/industry/${digest.slug}`);
    }
  };

  return (
    <Pressable
      onPress={goToDetail}
      style={({ pressed }) => [
        styles.card,
        {
          backgroundColor: pressed ? c.border : c.surface,
          borderColor: c.border,
          // Subtle highlight on the latest entry so the eye lands there first.
          borderLeftWidth: digest.is_latest ? 3 : StyleSheet.hairlineWidth,
          borderLeftColor: digest.is_latest ? c.brand : c.border,
        },
      ]}
    >
      <View style={styles.headerRow}>
        <Text style={[styles.eyebrow, { color: digest.is_latest ? c.brand : c.textMuted }]}>
          {eyebrow}
        </Text>
        <Text style={[styles.count, { color: c.textMuted }]}>
          {digest.ticker_count} {digest.ticker_count === 1 ? 'ticker' : 'tickers'}
        </Text>
      </View>
      <Text style={[styles.headline, { color: c.textPrimary }]}>
        {digest.industries.join(', ') || 'Mixed'} · {digest.date}
      </Text>
      {teaser ? (
        <Text style={[styles.teaser, { color: c.textPrimary }]} numberOfLines={3}>
          {teaser}
        </Text>
      ) : null}
      <Text style={[styles.cta, { color: c.brand }]}>
        {digest.is_latest ? 'Tap for full summary →' : 'View tickers →'}
      </Text>
    </Pressable>
  );
}


const styles = StyleSheet.create({
  card: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  eyebrow: {
    fontSize: fontSize.xs - 1,
    fontWeight: '700',
    letterSpacing: 1.5,
  },
  count: {
    fontSize: fontSize.xs,
    letterSpacing: 0.5,
  },
  headline: {
    fontSize: fontSize.lg,
    fontWeight: '700',
    marginTop: 6,
  },
  teaser: {
    fontSize: fontSize.sm,
    lineHeight: 20,
    marginTop: spacing.sm,
  },
  cta: {
    fontSize: fontSize.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
    marginTop: spacing.md,
  },
});
