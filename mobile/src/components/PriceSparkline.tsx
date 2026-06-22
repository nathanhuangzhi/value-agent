/**
 * Tiny inline sparkline showing 1-year monthly price history.
 * Used in TickerRow on the digest screen in place of the Mcap column.
 * Fetches from the shared price-history cache — no duplicate requests
 * if the ticker was already prefetched.
 */
import { useEffect, useState } from 'react';
import { View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { usePriceHistory } from '@/api/hooks';
import { useColors } from '@/theme/colors';

const W = 54;
const H = 28;
const PAD = 2;

export function PriceSparkline({ ticker, delay = 0 }: { ticker: string; delay?: number }) {
  const c = useColors();
  const [ready, setReady] = useState(delay === 0);
  useEffect(() => {
    if (delay === 0) return;
    const t = setTimeout(() => setReady(true), delay);
    return () => clearTimeout(t);
  }, [delay]);

  const { data } = usePriceHistory(ready ? ticker : undefined);

  if (!data || data.data.length < 2) {
    return <View style={{ width: W, height: H }} />;
  }

  // Filter to last 12 months of monthly data.
  const cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - 1);
  const cutoffISO = cutoff.toISOString().slice(0, 10);
  const pts = data.data.filter((p) => p.date >= cutoffISO && p.close > 0);

  if (pts.length < 2) {
    return <View style={{ width: W, height: H }} />;
  }

  const values = pts.map((p) => p.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const chartW = W - PAD * 2;
  const chartH = H - PAD * 2;

  const svgPts = pts.map((p, i) => ({
    x: PAD + (i / (pts.length - 1)) * chartW,
    y: PAD + (1 - (p.close - min) / range) * chartH,
  }));

  const d = svgPts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');

  const isUp = values[values.length - 1] >= values[0];
  const color = isUp ? c.positive : c.negative;

  return (
    <Svg width={W} height={H}>
      <Path
        d={d}
        stroke={color}
        strokeWidth={1.5}
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </Svg>
  );
}
