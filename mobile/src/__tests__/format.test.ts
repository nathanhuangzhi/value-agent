import { formatMoney, formatPct, formatRatio } from '@/utils/format';

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
