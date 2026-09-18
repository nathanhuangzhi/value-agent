/**
 * Generic chart for a user-defined spec: 1–4 series over the same periods,
 * each drawn as bars or a line on the left or right axis. Bars share the
 * slot for a period (grouped); negative bars hang below zero in red;
 * a line skips missing points. Touch shows the values for one period.
 */
import { useMemo, useState } from 'react';
import { StyleSheet, Text, View, type GestureResponderEvent, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import { formatMetric, type MetricFormat } from '@/api/metrics';
import { useColors, fontSize, spacing } from '@/theme/colors';

export type ChartSeries = { label: string; kind: 'line' | 'bar'; axis: 'left' | 'right'; format: MetricFormat; values: (number | null)[] };

const H = 200;
const PAD = { top: 12, right: 44, bottom: 26, left: 44 };
const PALETTE = ['#1F5F3B', '#175CD3', '#B54708', '#7A5AF8'];

function scale(values: (number | null)[][]): { min: number; max: number } {
  const all = values.flat().filter((v): v is number => v != null && isFinite(v));
  if (!all.length) return { min: 0, max: 1 };
  let min = Math.min(0, ...all), max = Math.max(0, ...all);
  if (min === max) max = min + 1;
  const pad = (max - min) * 0.06;
  return { min: min < 0 ? min - pad : 0, max: max + pad };
}

export function SeriesChart({ periods, series, period }: { periods: string[]; series: ChartSeries[]; period: 'quarterly' | 'annual' }) {
  const c = useColors();
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  const n = periods.length;
  const chartW = Math.max(0, width - PAD.left - PAD.right);
  const chartH = H - PAD.top - PAD.bottom;
  const left = useMemo(() => scale(series.filter((s) => s.axis === 'left').map((s) => s.values)), [series]);
  const right = useMemo(() => scale(series.filter((s) => s.axis === 'right').map((s) => s.values)), [series]);
  const hasRight = series.some((s) => s.axis === 'right');
  const slot = n ? chartW / n : 0;
  const x = (i: number) => PAD.left + slot * (i + 0.5);
  const y = (v: number, axis: 'left' | 'right') => {
    const sc = axis === 'left' ? left : right;
    return PAD.top + (1 - (v - sc.min) / (sc.max - sc.min)) * chartH;
  };
  const bars = series.filter((s) => s.kind === 'bar');
  const barW = bars.length ? Math.max(2, (slot * 0.7) / bars.length) : 0;

  const onTouch = (e: GestureResponderEvent) => {
    if (!slot) return;
    const i = Math.floor((e.nativeEvent.locationX - PAD.left) / slot);
    setActive(Math.max(0, Math.min(n - 1, i)));
  };
  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);
  const label = (p: string) => (period === 'annual' ? `FY${p.slice(2, 4)}` : `${p.slice(2, 4)}Q${Math.ceil(parseInt(p.slice(5, 7), 10) / 3)}`);
  const tickEvery = n > 12 ? Math.ceil(n / 8) : n > 8 ? 2 : 1;

  return (
    <View onLayout={onLayout} onStartShouldSetResponder={() => true} onResponderGrant={onTouch} onResponderMove={onTouch} onResponderRelease={() => setActive(null)}>
      {width > 0 ? (
        <Svg width={width} height={H}>
          {/* zero lines */}
          <Line x1={PAD.left} x2={width - PAD.right} y1={y(0, 'left')} y2={y(0, 'left')} stroke={c.border} strokeWidth={1} />
          {/* axis labels */}
          {[left.max, left.min].map((v, k) => (
            <SvgText key={`l${k}`} x={PAD.left - 4} y={y(v, 'left') + (k ? 0 : 10)} fontSize={9} fill={c.textMuted} textAnchor="end">
              {formatMetric(v, series.find((s) => s.axis === 'left')?.format ?? 'number')}
            </SvgText>
          ))}
          {hasRight ? [right.max, right.min].map((v, k) => (
            <SvgText key={`r${k}`} x={width - PAD.right + 4} y={y(v, 'right') + (k ? 0 : 10)} fontSize={9} fill={c.textMuted} textAnchor="start">
              {formatMetric(v, series.find((s) => s.axis === 'right')?.format ?? 'number')}
            </SvgText>
          )) : null}
          {/* bars */}
          {bars.map((s, si) => s.values.map((v, i) => {
            if (v == null) return null;
            const color = PALETTE[series.indexOf(s) % PALETTE.length];
            const y0 = y(0, s.axis), y1 = y(v, s.axis);
            const bx = x(i) - (bars.length * barW) / 2 + si * barW;
            return <Rect key={`${si}-${i}`} x={bx} y={Math.min(y0, y1)} width={barW - 1} height={Math.max(1, Math.abs(y1 - y0))}
              fill={v < 0 ? c.negative : color} opacity={active == null || active === i ? 0.95 : 0.45} rx={1.5} />;
          }))}
          {/* lines */}
          {series.map((s, si) => {
            if (s.kind !== 'line') return null;
            const color = PALETTE[si % PALETTE.length];
            let d = '', pen = false;
            s.values.forEach((v, i) => {
              if (v == null) { pen = false; return; }
              d += `${pen ? 'L' : 'M'} ${x(i).toFixed(1)} ${y(v, s.axis).toFixed(1)} `;
              pen = true;
            });
            return (
              <Path key={si} d={d} stroke={color} strokeWidth={2} fill="none" strokeLinejoin="round" strokeDasharray={s.axis === 'right' ? '4,3' : undefined} />
            );
          })}
          {active != null ? (
            <>
              <Line x1={x(active)} x2={x(active)} y1={PAD.top} y2={H - PAD.bottom} stroke={c.textMuted} strokeWidth={1} strokeDasharray="3,3" />
              {series.map((s, si) => s.kind === 'line' && s.values[active] != null ? (
                <Circle key={si} cx={x(active)} cy={y(s.values[active] as number, s.axis)} r={3.5} fill={PALETTE[si % PALETTE.length]} />
              ) : null)}
            </>
          ) : null}
          {/* x ticks */}
          {periods.map((p, i) => (i % tickEvery === 0 || i === n - 1) ? (
            <SvgText key={p} x={x(i)} y={H - 8} fontSize={9} fill={c.textMuted} textAnchor="middle">{label(p)}</SvgText>
          ) : null)}
        </Svg>
      ) : <View style={{ height: H }} />}
      <View style={styles.legend}>
        {series.map((s, si) => (
          <View key={si} style={styles.legendItem}>
            <View style={[styles.swatch, { backgroundColor: PALETTE[si % PALETTE.length], borderRadius: s.kind === 'bar' ? 2 : 4 }]} />
            <Text style={[styles.legendText, { color: c.textMuted }]}>
              {s.label}{s.axis === 'right' ? ' (right)' : ''}{active != null ? `: ${formatMetric(s.values[active], s.format)}` : ''}
            </Text>
          </View>
        ))}
        {active != null ? <Text style={[styles.legendText, { color: c.textPrimary, fontWeight: '700' }]}>{label(periods[active])}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md, paddingHorizontal: 4, paddingTop: 2 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  swatch: { width: 10, height: 10 },
  legendText: { fontSize: fontSize.xs },
});
