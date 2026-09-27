/**
 * The valuation series is computed in the app from USD statements and a close
 * quoted in the stock's own currency — a CNY-quoted A-share must divide the
 * close, or every multiple comes out ~6.7x too high (the bug that made
 * 宇通客车's Static P/E disagree with the KPI grid's).
 */
import { computeValuationHistory } from '@/utils/valuationHistory';
import { formatStockPrice } from '@/utils/format';
import type { Statements } from '@/api/types';

const annual: Statements = {
  income_statement: [
    { period: '2025-12-31', items: { 'Net Income': 100, 'Total Revenue': 1000 }, sources: {} },
  ],
  balance_sheet: [
    { period: '2025-12-31', items: { 'Common Stock Equity': 500 }, sources: {} },
  ],
  cash_flow: [],
} as unknown as Statements;

const quarterly: Statements = {
  income_statement: [
    { period: '2026-06-30', items: { 'Diluted Average Shares': 1000 }, sources: {} },
  ],
  balance_sheet: [
    { period: '2026-06-30', items: { 'Common Stock Equity': 500 }, sources: {} },
  ],
  cash_flow: [],
} as unknown as Statements;

const prices = [{ date: '2026-09-01', close: 6.7125 }];

test('a USD quote is unchanged', () => {
  const [pt] = computeValuationHistory(annual, quarterly, prices, 1);
  expect(pt.static_pe).toBeCloseTo((6.7125 * 1000) / 100);
  expect(pt.price).toBeCloseTo(6.7125);
});

test('a CNY quote is converted before the multiple is taken', () => {
  const [pt] = computeValuationHistory(annual, quarterly, prices, 6.7125);
  expect(pt.static_pe).toBeCloseTo(10);          // (6.7125 / 6.7125) × 1000 / 100
  expect(pt.static_ps).toBeCloseTo(1);
  expect(pt.pb).toBeCloseTo(2);
  // The price line keeps the quoted figure — that IS the share price.
  expect(pt.price).toBeCloseTo(6.7125);
});

test('the divisor defaults to 1 and ignores nonsense', () => {
  const base = computeValuationHistory(annual, quarterly, prices)[0];
  expect(base.static_pe).toBeCloseTo(67.125);
  for (const bad of [0, -1, NaN, Infinity]) {
    expect(computeValuationHistory(annual, quarterly, prices, bad)[0].static_pe).toBeCloseTo(67.125);
  }
});

test('a price is labelled in the currency it trades in', () => {
  expect(formatStockPrice(26.01, 'CNY')).toBe('¥26.0');
  expect(formatStockPrice(4.5, 'USD')).toBe('$4.50');
  expect(formatStockPrice(4.5)).toBe('$4.50');
  expect(formatStockPrice(null, 'CNY')).toBe('—');
});
