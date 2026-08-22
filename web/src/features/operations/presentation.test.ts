import { describe, expect, it } from 'vitest';

import {
  operationsAttentionResolutionLabel,
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
});
