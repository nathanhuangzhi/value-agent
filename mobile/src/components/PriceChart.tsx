/**
 * Interactive 5-year monthly price chart drawn as an SVG path.
 *
 * Features:
 *   - Auto-themed: green stroke if 5y change is positive, red if negative
 *   - Soft gradient fill underneath
 *   - Touch + drag along the chart to inspect a specific month — a marker
 *     dot tracks the touch position and the date/price label updates
 *   - Y-axis labels (min/max) on the right edge
 *   - X-axis year labels at the bottom
 *
 * Falls back gracefully: empty/short data shows a "(no chart data)" stub
 * rather than throwing.
 */
import { useMemo, useState } from 'react';
import {
  GestureResponderEvent,
  LayoutChangeEvent,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import type { PricePoint } from '@/api/types';
import { useColors, fontSize, spacing } from '@/theme/colors';
import { formatStockPrice } from '@/utils/format';

const PADDING = { top: 16, right: 48, bottom: 28, left: 12 };
const CHART_HEIGHT = 200;
// Hard cap on how far back we plot. Above 10 years, the visual story is
// usually noise (M&A jumps, share splits, regime changes) that doesn't
// help a value investor decide today.
const MAX_YEARS = 10;
// Target chart resolution after the 10-year cap. The series is
// downsampled to this many points when the post-cap source is longer
// (e.g. 10 years × 12 months = 120 → step=2 → bi-monthly). Keeps the
// SVG path short and touch resolution ~5px per point on a phone.
const TARGET_POINTS = 80;


function downsample<T>(arr: T[], target: number): T[] {
  if (arr.length <= target) return arr;
  const step = Math.ceil(arr.length / target);
  const out: T[] = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[i]);
  // Always preserve the latest point even if it didn't land on a step boundary.
  const last = arr[arr.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  return out;
}


function yearsBetween(startISO: string, endISO: string): number {
  const start = new Date(startISO);
  const end = new Date(endISO);
  return (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24 * 365.25);
}


function formatDateLabel(iso: string): string {
  // 2025-12-01 → "Dec 2025"
  const m = iso.match(/^(\d{4})-(\d{2})/);
  if (!m) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[parseInt(m[2]) - 1]} ${m[1]}`;
}


export function PriceChart({ data }: { data: PricePoint[] }) {
  const c = useColors();
  const [width, setWidth] = useState(0);
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  // 1) Drop nulls. 2) Cap to the last MAX_YEARS by date (not by point
  // count, so daily/weekly/monthly all behave correctly). 3) Downsample
  // to TARGET_POINTS so the line stays smooth and touch resolution is
  // ~5px per point on a phone.
  const series = useMemo(() => {
    const valid = data.filter((p) => p.close != null && isFinite(p.close));
    if (valid.length === 0) return valid;
    const lastDate = new Date(valid[valid.length - 1].date);
    const cutoff = new Date(lastDate);
    cutoff.setFullYear(cutoff.getFullYear() - MAX_YEARS);
    const cutoffISO = cutoff.toISOString().slice(0, 10);
    const recent = valid.filter((p) => p.date >= cutoffISO);
    return downsample(recent, TARGET_POINTS);
  }, [data]);

  if (series.length < 2) {
    return (
      <View style={[styles.empty, { backgroundColor: c.surface, borderColor: c.border }]}>
        <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>
          (no chart data)
        </Text>
      </View>
    );
  }

  const closes = series.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const chartW = Math.max(0, width - PADDING.left - PADDING.right);
  const chartH = CHART_HEIGHT - PADDING.top - PADDING.bottom;

  // Pre-compute x,y for every point.
  const points = useMemo(
    () =>
      series.map((p, i) => ({
        x: PADDING.left + (i / (series.length - 1)) * chartW,
        y: PADDING.top + (1 - (p.close - min) / range) * chartH,
      })),
    [series, chartW, chartH, min, range],
  );

  // SVG paths.
  const linePath = useMemo(
    () =>
      points.length === 0
        ? ''
        : points
            .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
            .join(' '),
    [points],
  );
  const fillPath = useMemo(() => {
    if (points.length === 0) return '';
    const baseline = CHART_HEIGHT - PADDING.bottom;
    const first = points[0];
    const last = points[points.length - 1];
    return `${linePath} L ${last.x.toFixed(2)} ${baseline} L ${first.x.toFixed(2)} ${baseline} Z`;
  }, [linePath, points]);

  // Direction-aware coloring: green if 5y up, red if 5y down.
  const stroke = closes[closes.length - 1] >= closes[0] ? c.positive : c.negative;

  // Year tick positions: first occurrence of each year in the series.
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

  // Touch handling — map touch X to a series index.
  function pickIndex(e: GestureResponderEvent): number {
    if (chartW <= 0) return 0;
    const x = e.nativeEvent.locationX - PADDING.left;
    const ratio = Math.max(0, Math.min(1, x / chartW));
    return Math.round(ratio * (series.length - 1));
  }
  function onLayout(e: LayoutChangeEvent) {
    setWidth(e.nativeEvent.layout.width);
  }
  function onTouch(e: GestureResponderEvent) {
    setActiveIdx(pickIndex(e));
  }
  function onEnd() {
    setActiveIdx(null);
  }

  // Tooltip label: active touch point if any, else the latest close.
  const tipIdx = activeIdx ?? series.length - 1;
  const tip = series[tipIdx];
  const tipPoint = points[tipIdx];

  // Range-aware % change vs first point (used in header). Years label is
  // computed from the actual data span, not hardcoded to 5y.
  const pctChange = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100;
  const spanYears = yearsBetween(series[0].date, series[series.length - 1].date);
  const rangeLabel = spanYears >= 1.5
    ? `${Math.round(spanYears)}Y`
    : `${Math.max(1, Math.round(spanYears * 12))}M`;

  return (
    <View onLayout={onLayout}>
      {/* Top-right value label */}
      <View style={styles.headerRow}>
        <View>
          <Text style={[styles.tipDate, { color: c.textMuted }]}>
            {formatDateLabel(tip.date)}
          </Text>
          <Text style={[styles.tipPrice, { color: c.textPrimary }]}>
            {formatStockPrice(tip.close)}
          </Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={[styles.changeLabel, { color: c.textMuted }]}>{rangeLabel}</Text>
          <Text style={[styles.changeValue, { color: pctChange >= 0 ? c.positive : c.negative }]}>
            {pctChange >= 0 ? '+' : ''}
            {pctChange.toFixed(1)}%
          </Text>
        </View>
      </View>

      {/* Chart */}
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
            {/* Fill area */}
            <Path d={fillPath} fill={stroke} fillOpacity={0.08} />
            {/* Line */}
            <Path d={linePath} stroke={stroke} strokeWidth={2} fill="none" strokeLinejoin="round" strokeLinecap="round" />

            {/* Vertical guide for active touch */}
            {activeIdx !== null && tipPoint && (
              <Line
                x1={tipPoint.x}
                y1={PADDING.top}
                x2={tipPoint.x}
                y2={CHART_HEIGHT - PADDING.bottom}
                stroke={c.textMuted}
                strokeWidth={1}
                strokeDasharray="2,3"
                opacity={0.6}
              />
            )}
            {/* Active touch dot */}
            {tipPoint && (
              <Circle
                cx={tipPoint.x}
                cy={tipPoint.y}
                r={activeIdx === null ? 3 : 5}
                fill={stroke}
                stroke={c.background}
                strokeWidth={1.5}
              />
            )}

            {/* Y-axis labels (max top, min bottom) on the right edge */}
            <SvgText
              x={width - PADDING.right + 6}
              y={PADDING.top + 4}
              fontSize={fontSize.xs}
              fill={c.textMuted}
            >
              {formatStockPrice(max)}
            </SvgText>
            <SvgText
              x={width - PADDING.right + 6}
              y={CHART_HEIGHT - PADDING.bottom - 1}
              fontSize={fontSize.xs}
              fill={c.textMuted}
            >
              {formatStockPrice(min)}
            </SvgText>

            {/* X-axis year labels — tick density adapts to the data span
                so longer histories don't overlap. Aim for ≤ 6 visible labels. */}
            {(() => {
              const step = yearTicks.length <= 6
                ? 1
                : yearTicks.length <= 12
                  ? 2
                  : yearTicks.length <= 20
                    ? 3
                    : 5;
              return yearTicks.filter((_, i) => i % step === 0);
            })().map((tick) => (
              <SvgText
                key={tick.year}
                x={tick.x}
                y={CHART_HEIGHT - 4}
                fontSize={fontSize.xs}
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
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginBottom: spacing.sm,
  },
  tipDate: {
    fontSize: fontSize.xs,
    letterSpacing: 0.5,
  },
  tipPrice: {
    fontSize: fontSize.xl,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    marginTop: 2,
  },
  changeLabel: {
    fontSize: fontSize.xs - 1,
    letterSpacing: 1,
  },
  changeValue: {
    fontSize: fontSize.md,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    marginTop: 2,
  },
  empty: {
    height: CHART_HEIGHT,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
  },
});
