import { afterEach, expect, test } from 'vitest';

import {
  formatCurrency,
  formatTimestamp,
  formatValuationTimestamp,
  hasValidValuationTimestamp,
  selectValuationTimestamp,
} from './format';

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

test('distinguishes missing valuation time from a valid as-of in either language', () => {
  for (const value of [
    null,
    undefined,
    '',
    'invalid',
    '1970-01-01T00:00:00Z',
    '1970-01-01T08:00:00+08:00',
  ]) {
    document.documentElement.lang = 'en';
    expect(hasValidValuationTimestamp(value)).toBe(false);
    expect(formatValuationTimestamp(value)).toBe('No valid valuation time');
    document.documentElement.lang = 'zh-CN';
    expect(formatValuationTimestamp(value)).toBe('尚无有效估值时间');
  }

  const valid = '2026-10-15T15:00:00+08:00';
  expect(hasValidValuationTimestamp(valid)).toBe(true);
  expect(formatValuationTimestamp(valid)).toBe(formatTimestamp(valid));
  // Other timestamp domains retain their ordinary formatting.
  expect(formatTimestamp('1970-01-01T00:00:00Z')).toBe('01/01 08:00');
});

test.each([
  null,
  undefined,
  '1970-01-01T08:00:00+08:00',
  '2026-10-14T15:00:00+08:00',
])(
  'preserves the canonical valuation time instead of the newer read clock: %s',
  (asOf) => {
    expect(
      selectValuationTimestamp({
        valuation_as_of: asOf,
        valuation_timestamp: '2026-10-15T12:00:00+08:00',
      }),
    ).toBe(asOf);
  },
);

test('keeps the legacy timestamp only when the canonical field is absent', () => {
  expect(
    selectValuationTimestamp({
      valuation_timestamp: '2026-10-15T12:00:00+08:00',
    }),
  ).toBe('2026-10-15T12:00:00+08:00');
  expect(selectValuationTimestamp(undefined)).toBeUndefined();
});
