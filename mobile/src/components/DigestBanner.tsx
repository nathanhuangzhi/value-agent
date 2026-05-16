/**
 * Compact "today's batch" card for the home screen.
 *
 * Shows date + industry + ticker count + the first sentence of the LLM
 * summary. Tapping opens the full digest screen at `/digest`. Hidden
 * entirely (returns null) when no digest data exists — keeps the home
 * screen clean rather than rendering an empty stub.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import type { DigestResponse } from '@/api/types';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';


function firstSentence(md: string, max: number = 180): string {
  if (!md) return '';
  // Strip simple markdown markers (**, *, _, `) so the teaser reads cleanly.
  const stripped = md.replace(/[*_`]+/g, '').trim();
  // Take everything up to the first sentence-ender, capped at `max` chars.
  const match = stripped.match(/^.+?[.!?](\s|$)/);
  const candidate = match ? match[0].trim() : stripped;
  if (candidate.length <= max) return candidate;
  return candidate.slice(0, max - 1).trimEnd() + '…';
}


export function DigestBanner({ digest }: { digest: DigestResponse }) {
  const c = useColors();
  const router = useRouter();
  if (!digest || !digest.ticker_count) return null;

  const teaser = firstSentence(digest.summary_md);

  return (
    <Pressable
      onPress={() => router.push('/digest')}
      style={({ pressed }) => [
        styles.card,
        {
          backgroundColor: pressed ? c.border : c.surface,
          borderColor: c.border,
        },
      ]}
    >
      <View style={styles.headerRow}>
        <Text style={[styles.eyebrow, { color: c.brand }]}>TODAY'S BATCH</Text>
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
      <Text style={[styles.cta, { color: c.brand }]}>Tap to see all →</Text>
    </Pressable>
  );
}


const styles = StyleSheet.create({
  card: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
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
