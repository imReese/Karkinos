import { expect, test } from 'vitest';

import { formatStaleReason } from './stale-reason';

const staleReasonLabels = {
  noRealDataAvailable: '--',
  quoteTimestampMissing: '--',
  marketClosedCacheOnly: '--',
  refreshPolicyCacheOnly: '--',
  quoteOlderThanExpectedSession: '行情未及时更新（早于当前交易时段）',
  providerTimeout: '--',
  providerUnavailable: '--',
  sourceUnavailable: '--',
  tushareFundNavPermissionDenied:
    'TuShare fund_nav 权限不足，已切换盘中基金估值',
  confirmedFundNavMissingEstimateOnly: '确认净值缺失/估算中',
};

test('formats stale quote reason codes for chinese cockpit copy', () => {
  expect(
    formatStaleReason('quote_older_than_expected_session', staleReasonLabels),
  ).toBe('行情未及时更新（早于当前交易时段）');
});

test('keeps provider error text readable when it is not an internal code', () => {
  expect(
    formatStaleReason('TuShare fund_nav permission denied', staleReasonLabels),
  ).toBe('TuShare fund_nav permission denied');
});

test('formats tushare fund permission fallback reason for chinese cockpit copy', () => {
  expect(
    formatStaleReason('tushare_fund_nav_permission_denied', staleReasonLabels),
  ).toBe('TuShare fund_nav 权限不足，已切换盘中基金估值');
});

test('formats unconfirmed fund estimate reason for chinese cockpit copy', () => {
  expect(
    formatStaleReason(
      'confirmed_fund_nav_missing_estimate_only',
      staleReasonLabels,
    ),
  ).toBe('确认净值缺失/估算中');
});
