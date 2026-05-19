/**
 * Business overview block — mirrors `_render_business_bullets` in the web
 * renderer. Shows a one-line "What it does" summary followed by the 9
 * categorical attributes the Stage 2 classifier wrote out for this
 * ticker (sector, industry, revenue model, customers, asset intensity,
 * value chain position, geographic exposure, inventory strategy, global
 * presence).
 *
 * Layout is a vertical key-value list. Labels in muted bold left-aligned;
 * values inline next to them in primary text. Missing values are skipped
 * silently (rather than rendering "—" placeholders) since not every
 * classifier run populates every field.
 */
import { StyleSheet, Text, View } from 'react-native';

import { useColors, fontSize, spacing } from '@/theme/colors';


type Props = {
  classification: Record<string, string | null | undefined>;
  meta: { primary_category?: string; logic_summary?: string };
};


/** Labels mirror the web report's bullets, in the same order. */
const FIELDS: { key: string; label: string }[] = [
  { key: 'sector',                label: 'Sector' },
  { key: 'industry',              label: 'Industry' },
  { key: 'revenue_model',         label: 'Revenue model' },
  { key: 'customer_type',         label: 'Customers' },
  { key: 'asset_intensity',       label: 'Asset intensity' },
  { key: 'value_chain_position',  label: 'Value chain' },
  { key: 'geographic_exposure',   label: 'Geographic exposure' },
  { key: 'inventory_strategy',    label: 'Inventory strategy' },
  { key: 'global_presence',       label: 'Global presence' },
];


export function BusinessOverview({ classification, meta }: Props) {
  const c = useColors();
  const summary = (meta?.logic_summary || '').trim();

  const fieldsWithValues = FIELDS
    .map((f) => ({ ...f, value: (classification?.[f.key] || '').toString().trim() }))
    .filter((f) => f.value);

  if (!summary && fieldsWithValues.length === 0) {
    return (
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>
        (no business overview available)
      </Text>
    );
  }

  return (
    <View>
      {summary ? (
        <View style={[styles.row, styles.summaryRow]}>
          <Text style={[styles.label, { color: c.brand }]} numberOfLines={1}>
            What it does:
          </Text>
          <Text style={[styles.summary, { color: c.textPrimary }]}>{summary}</Text>
        </View>
      ) : null}

      {fieldsWithValues.map((f) => (
        <View key={f.key} style={styles.row}>
          <Text style={[styles.label, { color: c.textMuted }]} numberOfLines={1}>
            {f.label}
          </Text>
          <Text style={[styles.value, { color: c.textPrimary }]}>{f.value}</Text>
        </View>
      ))}
    </View>
  );
}


const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 6,
  },
  summaryRow: {
    marginBottom: spacing.md,
    flexDirection: 'column',
    alignItems: 'flex-start',
  },
  label: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    letterSpacing: 0.5,
    width: 130,
  },
  value: {
    fontSize: fontSize.sm,
    flex: 1,
  },
  summary: {
    fontSize: fontSize.md,
    lineHeight: 22,
    marginTop: 4,
  },
});
