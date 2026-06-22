import { expect, test } from 'vitest';

import { formatPublicStatus } from './public-labels';

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
