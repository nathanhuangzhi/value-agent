/**
 * Compact line chart for use in a multi-chart grid (e.g. the 2×2
 * Stock-Price / P/E / P/S / P/B layout on the ticker screen).
 *
 * Same visual language as `PriceChart` (gradient fill, year-tick x-axis,
 * tap-and-drag to inspect) but proportioned for ~half-width and reduced
 * detail — no min/max y-axis labels, smaller font sizes, simpler header.
 *
 * Caller supplies the data as a flat `{date, value}[]` series so the
 * same component can plot stock price, P/E, P/S, P/B, etc.
 */
import { useCallback, useMemo, useState } from 'react';
import {
  GestureResponderEvent,
  LayoutChangeEvent,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import { useColors, fontSize, spacing } from '@/theme/colors';


const PADDING = { top: 24, right: 6, bottom: 18, left: 6 };
const CHART_HEIGHT = 140;
const TARGET_POINTS = 60;
const MAX_YEARS = 10;


export type SeriesPoint = { date: string; value: number };

type Props = {
  title: string;
  /** Source series. Pre-filtered to non-null values is fine but not
   * required — the component filters internally. */
  data: SeriesPoint[];
  /** Color of the line + fill. Defaults to brand green. */
  color?: string;
  /** Formatter for the current-value label ("$50" or "12x" etc.). */
  format: (v: number) => string;
};


function downsample<T>(arr: T[], target: number): T[] {
  if (arr.length <= target) return arr;
  const step = Math.ceil(arr.length / target);
  const out: T[] = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[i]);
  const last = arr[arr.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  return out;
}


function tickStepForSpan(years: number): number {
  if (years >= 12) return 3;
  if (years >= 6) return 2;
  return 1;
}


export function MiniLineChart({ title, data, color, format }: Props) {
  const c = useColors();
  const stroke = color ?? c.brand;
  const [width, setWidth] = useState(0);
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  const series = useMemo(() => {
    const valid = data.filter((p) => p.value != null && isFinite(p.value));
    if (valid.length === 0) return valid;
    // Cap to last MAX_YEARS, then downsample for path resolution.
    const lastDate = new Date(valid[valid.length - 1].date);
    const cutoff = new Date(lastDate);
    cutoff.setFullYear(cutoff.getFullYear() - MAX_YEARS);
    const cutoffISO = cutoff.toISOString().slice(0, 10);
    return downsample(valid.filter((p) => p.date >= cutoffISO), TARGET_POINTS);
  }, [data]);

  if (series.length < 2) {
    return (
      <View style={[styles.empty, { backgroundColor: c.surface, borderColor: c.border }]}>
        <Text style={[styles.title, { color: c.textMuted }]}>{title}</Text>
        <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>(no data)</Text>
      </View>
    );
  }

  const values = series.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const chartW = Math.max(0, width - PADDING.left - PADDING.right);
  const chartH = CHART_HEIGHT - PADDING.top - PADDING.bottom;

  const points = useMemo(
    () =>
      series.map((p, i) => ({
        x: PADDING.left + (i / (series.length - 1)) * chartW,
        y: PADDING.top + (1 - (p.value - min) / range) * chartH,
      })),
    [series, chartW, chartH, min, range],
  );

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(' ');
  const baseline = CHART_HEIGHT - PADDING.bottom;
  const fillPath =
    points.length === 0
      ? ''
      : `${linePath} L ${points[points.length - 1].x.toFixed(2)} ${baseline} L ${points[0].x.toFixed(2)} ${baseline} Z`;

  // Year-axis ticks at the data span's first occurrence of each year.
  const yearTicks = useMemo(() => {
    const seen = new Set<string>();
    const ticks: { x: number; year: string }[] = [];
    for (let i = 0; i < series.length; i++) {
      const year = series[i].date.slice(0, 4);
      if (!seen.has(year)) {
        seen.add(year);
        ticks.push({ x: points[i]?.x ?? 0, year });
      }
    }
    return ticks;
  }, [series, points]);

  const spanYears =
    series.length > 1
      ? (new Date(series[series.length - 1].date).getTime() -
          new Date(series[0].date).getTime()) /
        (1000 * 60 * 60 * 24 * 365.25)
      : 1;
  const tickStep = tickStepForSpan(spanYears);

  // Touch handling — mirror PriceChart so the interaction feels the same.
  function pickIndex(e: GestureResponderEvent): number {
    if (chartW <= 0) return 0;
    const x = e.nativeEvent.locationX - PADDING.left;
    const ratio = Math.max(0, Math.min(1, x / chartW));
    return Math.round(ratio * (series.length - 1));
  }
  const onLayout = useCallback((e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width), []);
  const onTouch = useCallback((e: GestureResponderEvent) => setActiveIdx(pickIndex(e)), [chartW, series.length]);
  const onEnd = useCallback(() => setActiveIdx(null), []);

  const tipIdx = activeIdx ?? series.length - 1;
  const tip = series[tipIdx];
  const tipPoint = points[tipIdx];

  return (
    <View onLayout={onLayout} style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
      <View style={styles.headerRow}>
        <Text style={[styles.title, { color: c.textMuted }]} numberOfLines={1}>{title}</Text>
        <Text style={[styles.value, { color: c.textPrimary }]} numberOfLines={1}>
          {format(tip.value)}
        </Text>
      </View>

      <View
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={onTouch}
        onResponderMove={onTouch}
        onResponderRelease={onEnd}
        onResponderTerminate={onEnd}
      >
        {width > 0 && (
          <Svg width={width} height={CHART_HEIGHT}>
            <Path d={fillPath} fill={stroke} fillOpacity={0.08} />
            <Path d={linePath} stroke={stroke} strokeWidth={1.6} fill="none" strokeLinejoin="round" strokeLinecap="round" />

            {activeIdx !== null && tipPoint && (
              <Line
                x1={tipPoint.x}
                y1={PADDING.top}
                x2={tipPoint.x}
                y2={CHART_HEIGHT - PADDING.bottom}
                stroke={c.textMuted}
                strokeWidth={1}
                strokeDasharray="2,3"
                opacity={0.5}
              />
            )}
            {tipPoint && (
              <Circle
                cx={tipPoint.x}
                cy={tipPoint.y}
                r={activeIdx === null ? 2.5 : 4}
                fill={stroke}
                stroke={c.background}
                strokeWidth={1}
              />
            )}

            {yearTicks
              .filter((_, i) => i % tickStep === 0)
              .map((tick) => (
                <SvgText
                  key={tick.year}
                  x={tick.x}
                  y={CHART_HEIGHT - 4}
                  fontSize={fontSize.xs - 2}
                  fill={c.textMuted}
                  textAnchor="middle"
                >
                  {tick.year}
                </SvgText>
              ))}
          </Svg>
        )}
      </View>
    </View>
  );
}


const styles = StyleSheet.create({
  card: {
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.sm,
    paddingTop: 6,
  },
  title: {
    fontSize: fontSize.xs,
    letterSpacing: 0.5,
    fontWeight: '600',
    flex: 1,
  },
  value: {
    fontSize: fontSize.sm,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    marginLeft: spacing.xs,
  },
  empty: {
    height: CHART_HEIGHT,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.sm,
  },
});
