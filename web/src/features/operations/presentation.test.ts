import { describe, expect, it } from 'vitest';

import {
  operationsAttentionResolutionLabel,
  operationsLimitationLabel,
  operationsNextActionLabel,
} from './presentation';

describe('operations Account Truth presentation', () => {
  it('distinguishes a stale snapshot refresh from an account mismatch', () => {
    expect(
      operationsNextActionLabel('refresh_account_truth_snapshot', 'zh'),
    ).toBe('刷新当前账户事实快照');
    expect(
      operationsAttentionResolutionLabel(
        'current_account_truth_snapshot_required',
        'zh',
      ),
    ).toBe('当前完整的 Account Truth 快照已记录');
    expect(
      operationsNextActionLabel('resolve_account_truth_mismatch', 'zh'),
    ).toBe('处理账户事实不一致');
  });

  it('localizes subsystem limitations while preserving financial terms', () => {
    expect(
      operationsLimitationLabel(
        'Account truth is degraded by stale account or market evidence.',
        'zh',
      ),
    ).toBe('Account Truth 因账户或行情快照凭据过期而降级。');
    expect(
      operationsLimitationLabel(
        'Three fund NAV observations require confirmation.',
        'zh',
      ),
    ).toBe('有 3 笔基金 NAV 观测待确认。');
    expect(
      operationsLimitationLabel(
        'Paper/shadow results are simulated review evidence, not broker execution.',
        'zh',
      ),
    ).toBe('模拟与影子检验仅为仿真复核证据，非券商真实执行。');
    expect(
      operationsLimitationLabel(
        'Three fund NAV observations require confirmation.',
        'en',
      ),
    ).toBe('Three fund NAV observations require confirmation.');
  });

  it('maps broker environment action label', () => {
    expect(
      operationsNextActionLabel(
        'await_explicit_real_broker_environment_confirmation',
        'zh',
      ),
    ).toBe('等待明确的实盘券商环境确认');
  });
});
