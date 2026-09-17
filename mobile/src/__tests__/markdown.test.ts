import { hasTable, toPlainText } from '@/components/Markdown';

const MD = `## Summary
Revenue **grew** 5% (\`GAAP\`).

- first point
- second point

| Metric | 2025 | 2026 |
|---|---|---|
| Revenue | 1,000 | 1,050 |

Closing line.`;

describe('Markdown helpers', () => {
  test('hasTable spots pipe tables only', () => {
    expect(hasTable(MD)).toBe(true);
    expect(hasTable('a | b without outer pipes')).toBe(false);
    expect(hasTable('plain text')).toBe(false);
  });

  test('toPlainText strips markers, keeps list markers, flattens tables', () => {
    const plain = toPlainText(MD);
    expect(plain).toContain('Summary');
    expect(plain).toContain('Revenue grew 5% (GAAP).');
    expect(plain).not.toContain('**');
    expect(plain).toContain('• first point');
    expect(plain).toContain('Metric  ·  2025  ·  2026');
    expect(plain).toContain('Revenue  ·  1,000  ·  1,050');
    expect(plain).not.toContain('|---');
    expect(plain.endsWith('Closing line.')).toBe(true);
  });
});
