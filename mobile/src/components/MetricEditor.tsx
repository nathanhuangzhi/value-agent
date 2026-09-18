/**
 * Create / edit one custom metric: name, expression, format, and a live
 * preview against a sample company (the last eight quarters). The
 * vocabulary sheet lists every alias, suffix and function.
 */
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { formatMetric, metricsApi, type Aliases, type Metric, type MetricFormat, type PreviewResult } from '@/api/metrics';
import { useColors, fontSize, radii, spacing } from '@/theme/colors';

const FORMATS: { key: MetricFormat; label: string }[] = [
  { key: 'ratio', label: 'x' }, { key: 'pct', label: '%' }, { key: 'money', label: '$' }, { key: 'number', label: '#' }, { key: 'bool', label: '✓' },
];

export function MetricEditor({ metric, sampleTicker, onSaved, onCancel }: {
  metric: Metric | null;
  sampleTicker: string;
  onSaved: (m: Metric) => void;
  onCancel: () => void;
}) {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const [name, setName] = useState(metric?.name ?? '');
  const [expr, setExpr] = useState(metric?.expr ?? '');
  const [format, setFormat] = useState<MetricFormat | null>(metric?.format ?? null);
  const [ticker, setTicker] = useState(sampleTicker);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [help, setHelp] = useState<Aliases | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced live preview.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!expr.trim() || !ticker.trim()) { setPreview(null); return; }
    timer.current = setTimeout(() => {
      setPreviewing(true);
      metricsApi.preview(expr, ticker.trim())
        .then(setPreview)
        .catch((e) => setPreview({ error: String((e as Error).message ?? e) }))
        .finally(() => setPreviewing(false));
    }, 450);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [expr, ticker]);

  const openHelp = () => {
    setHelpOpen(true);
    if (!help) metricsApi.aliases().then(setHelp).catch(() => {});
  };

  const effectiveFormat: MetricFormat = format ?? (preview && 'format' in preview ? preview.format : 'number');

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = { name: name.trim() || expr.trim().slice(0, 40), expr: expr.trim(), format: format ?? undefined };
      const saved = metric ? await metricsApi.update(metric.id, body) : await metricsApi.create(body);
      onSaved(saved);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
      <Text style={[styles.title, { color: c.textPrimary }]}>{metric ? 'Edit metric' : 'New metric'}</Text>
      <TextInput value={name} onChangeText={setName} placeholder="Name (e.g. FCF margin)" placeholderTextColor={c.textMuted}
        style={[styles.input, { color: c.textPrimary, backgroundColor: c.background, borderColor: c.border }]} />
      <View style={styles.exprRow}>
        <TextInput value={expr} onChangeText={setExpr} placeholder="fcf.ttm / revenue.ttm" placeholderTextColor={c.textMuted}
          autoCapitalize="none" autoCorrect={false} multiline
          style={[styles.input, styles.expr, { color: c.textPrimary, backgroundColor: c.background, borderColor: c.border }]} />
        <Pressable onPress={openHelp} hitSlop={8} style={styles.helpBtn} accessibilityLabel="Vocabulary">
          <Ionicons name="help-circle-outline" size={22} color={c.brand} />
        </Pressable>
      </View>
      <View style={styles.formatRow}>
        <Text style={[styles.label, { color: c.textMuted }]}>Format</Text>
        {FORMATS.map((f) => (
          <Pressable key={f.key} onPress={() => setFormat(format === f.key ? null : f.key)}
            style={[styles.chip, { borderColor: c.border }, effectiveFormat === f.key && { backgroundColor: c.brand, borderColor: c.brand }]}>
            <Text style={[styles.chipText, { color: effectiveFormat === f.key ? '#fff' : c.textMuted }]}>{f.label}</Text>
          </Pressable>
        ))}
        {format === null ? <Text style={[styles.label, { color: c.textMuted }]}>auto</Text> : null}
      </View>

      <View style={[styles.preview, { borderColor: c.border }]}>
        <View style={styles.previewHead}>
          <Text style={[styles.label, { color: c.textMuted }]}>Preview on</Text>
          <TextInput value={ticker} onChangeText={(v) => setTicker(v.toUpperCase())} autoCapitalize="characters" autoCorrect={false}
            style={[styles.tickerInput, { color: c.textPrimary, borderColor: c.border }]} />
          {previewing ? <ActivityIndicator size="small" color={c.textMuted} /> : null}
        </View>
        {preview && 'error' in preview ? (
          <Text style={[styles.err, { color: c.negative }]}>{preview.error}</Text>
        ) : preview ? (
          <View>
            <Text style={[styles.latest, { color: c.textPrimary }]}>{formatMetric(preview.latest, effectiveFormat)}</Text>
            <View style={styles.seriesRow}>
              {preview.series.map((p) => (
                <View key={p.period} style={styles.seriesCell}>
                  <Text style={[styles.seriesVal, { color: p.value == null ? c.textMuted : c.textPrimary }]} numberOfLines={1} adjustsFontSizeToFit>
                    {formatMetric(p.value, effectiveFormat)}
                  </Text>
                  <Text style={[styles.seriesPeriod, { color: c.textMuted }]}>{p.period.slice(2, 7)}</Text>
                </View>
              ))}
            </View>
          </View>
        ) : (
          <Text style={[styles.label, { color: c.textMuted }]}>Type an expression to see it evaluated.</Text>
        )}
      </View>

      {error ? <Text style={[styles.err, { color: c.negative }]}>{error}</Text> : null}
      <View style={styles.actions}>
        <Pressable onPress={onCancel} hitSlop={8} style={styles.link}><Text style={[styles.linkText, { color: c.textMuted }]}>Cancel</Text></Pressable>
        <Pressable onPress={save} disabled={saving || !expr.trim() || (preview !== null && 'error' in preview)}
          style={[styles.btn, { backgroundColor: c.brand, opacity: saving || !expr.trim() || (preview !== null && 'error' in preview) ? 0.5 : 1 }]}>
          {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Save</Text>}
        </Pressable>
      </View>

      <Modal visible={helpOpen} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setHelpOpen(false)}>
        <View style={{ flex: 1, backgroundColor: c.background, paddingTop: spacing.md }}>
          <View style={[styles.helpHead, { borderBottomColor: c.border }]}>
            <Text style={[styles.title, { color: c.textPrimary, flex: 1 }]}>Vocabulary</Text>
            <Pressable onPress={() => setHelpOpen(false)} hitSlop={8}><Text style={[styles.linkText, { color: c.brand }]}>Done</Text></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: insets.bottom + spacing.xl }}>
            {help ? (
              <>
                <Text style={[styles.helpSection, { color: c.textMuted }]}>METRICS</Text>
                {help.metrics.map((m) => (
                  <Pressable key={m.alias} onPress={() => { setExpr((e) => (e ? `${e} ${m.alias}` : m.alias)); setHelpOpen(false); }} style={styles.helpRow}>
                    <Text style={[styles.helpAlias, { color: c.brand }]}>{m.alias}</Text>
                    <Text style={[styles.helpItem, { color: c.textMuted }]}>{m.item.startsWith('__') ? (m.alias === 'price' ? 'monthly close at period end' : 'price × diluted shares') : m.item} · {m.kind}</Text>
                  </Pressable>
                ))}
                <Text style={[styles.helpSection, { color: c.textMuted }]}>SHORTHANDS</Text>
                {Object.entries(help.derived).map(([k, v]) => (
                  <Pressable key={k} onPress={() => { setExpr((e) => (e ? `${e} ${k}` : k)); setHelpOpen(false); }} style={styles.helpRow}>
                    <Text style={[styles.helpAlias, { color: c.brand }]}>{k}</Text>
                    <Text style={[styles.helpItem, { color: c.textMuted }]}>{v}</Text>
                  </Pressable>
                ))}
                <Text style={[styles.helpSection, { color: c.textMuted }]}>SUFFIXES</Text>
                <Text style={[styles.helpItem, { color: c.textPrimary }]}>
                  .q single quarter (default) · .ttm trailing four quarters · .fy latest fiscal year · .yoy change vs a year ago · .abs
                </Text>
                <Text style={[styles.helpSection, { color: c.textMuted }]}>FUNCTIONS</Text>
                <Text style={[styles.helpItem, { color: c.textPrimary }]}>abs(x) · max(a, b) · min(a, b) · avg(x, n) · sum(x, n) · lag(x, n)</Text>
                <Text style={[styles.helpSection, { color: c.textMuted }]}>OPERATORS</Text>
                <Text style={[styles.helpItem, { color: c.textPrimary }]}>+ − × / ( ) &lt; &lt;= &gt; &gt;= == != and or not — a missing input makes that period blank; ÷ 0 is blank too.</Text>
              </>
            ) : <ActivityIndicator color={c.brand} />}
          </ScrollView>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.lg, padding: spacing.lg, gap: spacing.sm },
  title: { fontSize: fontSize.lg, fontWeight: '700' },
  input: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontSize: fontSize.md },
  exprRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  expr: { flex: 1, fontFamily: 'Menlo', minHeight: 44 },
  helpBtn: { paddingTop: 10 },
  formatRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  label: { fontSize: fontSize.xs, fontWeight: '600', letterSpacing: 0.5 },
  chip: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 3 },
  chipText: { fontSize: fontSize.xs, fontWeight: '700' },
  preview: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radii.md, padding: spacing.md, gap: spacing.sm },
  previewHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  tickerInput: { borderBottomWidth: 1, minWidth: 64, fontSize: fontSize.sm, fontWeight: '700', paddingVertical: 2 },
  latest: { fontSize: 22, fontWeight: '700', fontVariant: ['tabular-nums'] },
  seriesRow: { flexDirection: 'row', gap: 4, marginTop: 4 },
  seriesCell: { flex: 1, alignItems: 'center' },
  seriesVal: { fontSize: fontSize.xs, fontVariant: ['tabular-nums'] },
  seriesPeriod: { fontSize: 9, marginTop: 2 },
  err: { fontSize: fontSize.sm },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: spacing.lg, marginTop: spacing.xs },
  link: { paddingVertical: 6 },
  linkText: { fontSize: fontSize.sm, fontWeight: '600' },
  btn: { borderRadius: radii.pill, paddingHorizontal: spacing.lg, paddingVertical: 10, minWidth: 90, alignItems: 'center' },
  btnText: { color: '#fff', fontWeight: '700', fontSize: fontSize.sm },
  helpHead: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: spacing.md, paddingBottom: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  helpSection: { fontSize: fontSize.xs, fontWeight: '700', letterSpacing: 1, marginTop: spacing.md, marginBottom: 4 },
  helpRow: { paddingVertical: 5 },
  helpAlias: { fontFamily: 'Menlo', fontSize: fontSize.sm, fontWeight: '700' },
  helpItem: { fontSize: fontSize.xs, lineHeight: 18 },
});
