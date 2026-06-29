import { afterEach, expect, test } from 'vitest';

import { formatCurrency } from './format';

afterEach(() => {
  document.documentElement.lang = '';
});

test('formats CNY as a stable yen symbol in English UI', () => {
  document.documentElement.lang = 'en';

  expect(formatCurrency(1234.5)).toBe('¥1,234.50');
  expect(formatCurrency(-12.3)).toBe('-¥12.30');
  expect(formatCurrency(1234.5)).not.toContain('CN');
});

test('keeps the same CNY symbol in Chinese UI', () => {
  document.documentElement.lang = 'zh-CN';

  expect(formatCurrency(1234.5)).toBe('¥1,234.50');
});
