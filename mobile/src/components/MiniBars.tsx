/**
 * Four tiny bars for a per-quarter multiple (P/QE, P/QFCF) inside a list
 * row. Heights scale to the largest |value| in the cell, capped so one
 * blow-out quarter doesn't flatten the rest; negative quarters hang below
 * the baseline in red; missing quarters are a faint stub.
 */
import { StyleSheet, View } from 'react-native';

import { useColors } from '@/theme/colors';

const H = 22;          // total cell height
const CAP = 80;        // |multiple| above this is drawn as a full bar

export function MiniBars({ values, width = 40 }: { values: (number | null)[]; width?: number }) {
  const c = useColors();
  const abs = values.map((v) => (v == null ? 0 : Math.min(Math.abs(v), CAP)));
  const max = Math.max(...abs, 1);
  const gap = 3;
  const w = Math.max(4, Math.floor((width - gap * (values.length - 1)) / values.length));
  const posH = H * 0.7, negH = H * 0.3;
  return (
    <View style={[styles.wrap, { width, height: H }]} accessibilityLabel={values.map((v) => (v == null ? '—' : v.toFixed(0))).join(', ')}>
      {values.map((v, i) => {
        if (v == null) {
          return <View key={i} style={[styles.bar, { width: w, height: 2, bottom: negH, backgroundColor: c.border }]} />;
        }
        const h = Math.max(2, (abs[i] / max) * (v >= 0 ? posH : negH));
        return (
          <View
            key={i}
            style={[
              styles.bar,
              { width: w, height: h, backgroundColor: v >= 0 ? c.brand : c.negative },
              v >= 0 ? { bottom: negH } : { top: posH },
            ]}
          />
        );
      })}
      <View style={[styles.baseline, { bottom: negH, backgroundColor: c.border }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end', position: 'relative' },
  bar: { position: 'relative', borderRadius: 1.5 },
  baseline: { position: 'absolute', left: 0, right: 0, height: StyleSheet.hairlineWidth },
});
