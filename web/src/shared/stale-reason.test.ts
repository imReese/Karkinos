import { expect, test } from 'vitest';

import { copy } from '../app/copy';
import { formatStaleReason } from './stale-reason';

test('formats stale quote reason codes for chinese cockpit copy', () => {
  expect(
    formatStaleReason(
      'quote_older_than_expected_session',
      copy.zh.common.staleReasons,
    ),
  ).toBe('行情未及时更新（早于当前交易时段）');
});

test('keeps provider error text readable when it is not an internal code', () => {
  expect(
    formatStaleReason(
      'TuShare fund_nav permission denied',
      copy.zh.common.staleReasons,
    ),
  ).toBe('TuShare fund_nav permission denied');
});

test('formats tushare fund permission fallback reason for chinese cockpit copy', () => {
  expect(
    formatStaleReason(
      'tushare_fund_nav_permission_denied',
      copy.zh.common.staleReasons,
    ),
  ).toBe('TuShare fund_nav 权限不足，已切换 Eastmoney 基金估算源');
});

test('formats unconfirmed fund estimate reason for chinese cockpit copy', () => {
  expect(
    formatStaleReason(
      'confirmed_fund_nav_missing_estimate_only',
      copy.zh.common.staleReasons,
    ),
  ).toBe('确认净值缺失/估算中');
});
