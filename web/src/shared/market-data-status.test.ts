import { expect, test } from 'vitest';

import {
  formatMarketDataStatusNextAction,
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from './market-data-status';

test('normalizes frontend market-data status aliases into the shared v0.9 vocabulary', () => {
  expect(normalizeMarketDataStatus('confirmed NAV missing')).toBe(
    'confirmed_nav_missing',
  );
  expect(normalizeMarketDataStatus('cache_only')).toBe('cache');
  expect(normalizeMarketDataStatus('cached')).toBe('cache');
  expect(normalizeMarketDataStatus('quote_older_than_expected_session')).toBe(
    'stale',
  );
  expect(
    normalizeMarketDataStatus('confirmed_fund_nav_missing_estimate_only'),
  ).toBe('confirmed_nav_missing');
});

test('identifies confirmed, cache-like, and unconfirmed market-data statuses', () => {
  expect(isConfirmedMarketDataStatus('confirmed')).toBe(true);
  expect(isConfirmedMarketDataStatus('live')).toBe(true);
  expect(isConfirmedMarketDataStatus('healthy')).toBe(true);
  expect(isConfirmedMarketDataStatus('estimated')).toBe(false);

  expect(isCacheLikeMarketDataStatus('cache_only')).toBe(true);
  expect(isCacheLikeMarketDataStatus('stale')).toBe(true);
  expect(isCacheLikeMarketDataStatus('confirmed_nav_missing')).toBe(false);

  expect(isUnconfirmedMarketDataStatus('cache')).toBe(true);
  expect(isUnconfirmedMarketDataStatus('estimated')).toBe(true);
  expect(isUnconfirmedMarketDataStatus('missing')).toBe(true);
  expect(isUnconfirmedMarketDataStatus('confirmed_nav_missing')).toBe(true);
  expect(isUnconfirmedMarketDataStatus('live')).toBe(false);
  expect(isUnconfirmedMarketDataStatus(undefined)).toBe(false);
});

test('formats user-readable next actions for unconfirmed market-data statuses', () => {
  expect(formatMarketDataStatusNextAction('confirmed', 'zh')).toBeNull();
  expect(formatMarketDataStatusNextAction('cache', 'zh')).toBe(
    '刷新行情或检查数据源',
  );
  expect(
    formatMarketDataStatusNextAction('quote_older_than_expected_session', 'zh'),
  ).toBe('刷新行情或检查数据源');
  expect(formatMarketDataStatusNextAction('estimated', 'zh')).toBe(
    '等待确认数据或刷新行情',
  );
  expect(formatMarketDataStatusNextAction('confirmed_nav_missing', 'zh')).toBe(
    '等待基金确认净值或同步净值',
  );
  expect(formatMarketDataStatusNextAction('missing', 'en')).toBe(
    'Backfill market data or run the first sync',
  );
});
