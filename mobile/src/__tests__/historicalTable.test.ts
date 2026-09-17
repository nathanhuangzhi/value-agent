import type { Period } from '@/api/types';
import {
  computeHistoricalTableColumns,
  formatMoneyCell,
  fyLabel,
  latestAtOrBefore,
  quarterLabel,
  topAssetKeys,
  topLiabilityKeys,
  yoyDelta,
} from '@/lib/historicalTable';

const period = (p: string, items: Record<string, number | null>): Period => ({ period: p, items, sources: {} } as Period);

describe('historical table model', () => {
  test('labels', () => {
    expect(fyLabel('2025')).toBe("FY25");
    expect(quarterLabel('2026-06-30')).toBe("Q2'26");
  });

  test('money cells are compact and signed', () => {
    expect(formatMoneyCell(1_234_000_000)).toMatch(/1,234|1\.2B/);
    expect(formatMoneyCell(-5_000_000)).toMatch(/^-|\(/);
  });

  test('yoy delta and latest-at-or-before', () => {
    expect(yoyDelta(120, 100)).toBeCloseTo(0.2);
    expect(yoyDelta(100, 0)).toBeNull();
    const periods = [period('2023', { 'Net Income': 1 }), period('2024', { 'Net Income': 2 }), period('2025', { 'Net Income': null })];
    expect(latestAtOrBefore(periods, '2025-12-31', ['Net Income'])).toBe(2);
  });

  test('asset and liability rows are ranked by size and deduped by category', () => {
    const bs = [period('2025-12-31', {
      'Goodwill': 50, 'Other Intangible Assets': 40, 'Net PPE': 300, 'Receivables': 200, 'Inventory': 10,
      'Total Liabilities Net Minority Interest': 900, 'Long Term Debt': 400, 'Current Debt': 100, 'Accounts Payable': 250,
    })];
    const assets = topAssetKeys([], bs);
    expect(assets[0]).toBe('Net PPE');
    expect(assets).toContain('Receivables');
    const liabilities = topLiabilityKeys([], bs, 3);
    expect(liabilities.length).toBeLessThanOrEqual(3);
    expect(liabilities[0]).toBe('Long Term Debt');
  });

  test('columns: annual then quarterly with the divider between', () => {
    const stmts = (ps: string[]) => ({ income_statement: ps.map((p) => period(p, {})), balance_sheet: [], cash_flow: [] });
    const { columns, dividerIdx } = computeHistoricalTableColumns(stmts(['2023', '2024', '2025']) as never, stmts(['2026-03-31', '2026-06-30']) as never);
    expect(columns.map((c) => c.label)).toEqual(['FY23', 'FY24', 'FY25', "Q1'26", "Q2'26"]);
    expect(dividerIdx).toBe(3);
  });
});
