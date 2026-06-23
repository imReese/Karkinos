import { expect, test } from 'vitest';

import {
  formatPublicCode,
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicStatus,
} from './public-labels';

test('formats the shared v0.9 market-data statuses without leaking internal codes', () => {
  expect(formatPublicStatus('confirmed', 'zh')).toBe('已确认');
  expect(formatPublicStatus('live', 'zh')).toBe('实时行情');
  expect(formatPublicStatus('cache', 'zh')).toBe('缓存行情');
  expect(formatPublicStatus('estimated', 'zh')).toBe('估算中');
  expect(formatPublicStatus('missing', 'zh')).toBe('缺失');
  expect(formatPublicStatus('stale', 'zh')).toBe('行情过期');
  expect(formatPublicStatus('confirmed_nav_missing', 'zh')).toBe(
    '确认净值缺失',
  );

  expect(formatPublicStatus('confirmed_nav_missing', 'en')).toBe(
    'Confirmed NAV missing',
  );
});

test('formats generated operational notes without exposing internal ids', () => {
  expect(
    formatPublicOperationalNote('Prepared from signal action 42.', 'en'),
  ).toBe('Prepared from Decision action queue.');
  expect(
    formatPublicOperationalNote('Prepared from signal action 42.', 'zh'),
  ).toBe('已从决策待办生成手工确认订单。');
  expect(formatPublicOperationalNote('confirmed by operator', 'en')).toBe(
    'confirmed by operator',
  );
});

test('formats account-truth reconciliation categories without raw field labels', () => {
  expect(formatPublicCode('cash', 'zh')).toBe('现金');
  expect(formatPublicCode('position', 'zh')).toBe('持仓');
  expect(formatPublicCode('fee', 'zh')).toBe('费用');
  expect(formatPublicCode('cost_basis', 'zh')).toBe('成本价');

  expect(formatPublicCode('position', 'en')).toBe('Position');
  expect(formatPublicCode('cost_basis', 'en')).toBe('Cost basis');
});

test('formats research limitation notes for Chinese user-facing surfaces', () => {
  expect(
    formatPublicNote(
      'Validation evidence is not investment advice or a profitability guarantee.',
      'zh',
    ),
  ).toBe('验证证据不构成投资建议，也不保证收益。');
});
