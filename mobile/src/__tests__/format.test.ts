import { formatMetric } from '@/api/metrics';
import { currencySymbol, formatMoney, formatPct, formatRatio } from '@/utils/format';

describe('formatters', () => {
  test('money scales with magnitude', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(1.23e12)).toBe('$1.2T');
    expect(formatMoney(6.98e9)).toBe('$7.0B');
    expect(formatMoney(-4.5e8)).toBe('$-450M');
    expect(formatMoney(12_345)).toBe('$12K');
    expect(formatMoney(999)).toBe('$999');
  });
  test('ratios and percentages keep one decimal when small', () => {
    expect(formatRatio(8.34)).toBe('8.3x');
    expect(formatRatio(12.4)).toBe('12x');
    expect(formatRatio(undefined)).toBe('—');
    expect(formatPct(0.0567)).toBe('5.7%');
    expect(formatPct(0.25)).toBe('25%');
  });
});

describe('currency-aware money', () => {
  test('defaults to dollars so list views are unchanged', () => {
    expect(formatMoney(6.98e9)).toBe('$7.0B');
    expect(formatMoney(6.98e9, 'USD')).toBe('$7.0B');
  });

  test('an A-share shows yuan', () => {
    // 宇通客车: $8.58B × 6.7125 = ¥57.6B
    expect(formatMoney(57.58e9, 'CNY')).toBe('¥57.6B');
    expect(formatMoney(12_345, 'CNY')).toBe('¥12K');
    expect(currencySymbol('cny')).toBe('¥');
    expect(currencySymbol(null)).toBe('$');
  });

  test('an unknown code degrades to a bare number, never a wrong symbol', () => {
    expect(formatMoney(1e9, 'XYZ')).toBe('1.0B');
  });
});

describe('chart and custom-metric values follow the page currency', () => {
  test('money carries the currency symbol, other formats are currency-free', () => {
    expect(formatMetric(41.4e9, 'money', 'CNY')).toBe('¥41.40B');
    expect(formatMetric(6.17e9, 'money')).toBe('$6.17B');
    expect(formatMetric(0.2535, 'pct', 'CNY')).toBe('25%');
    expect(formatMetric(10.4959, 'ratio', 'CNY')).toBe('10.5x');
    expect(formatMetric(null, 'money', 'CNY')).toBe('—');
  });
});
