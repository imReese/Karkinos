import { expect, test } from 'vitest';

import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicReviewActionLabel,
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
  expect(formatPublicOperationalNote('confirmed by operator', 'zh')).toBe(
    '待人工复核说明',
  );
});

test('formats dotted operational note codes as generic review notes', () => {
  expect(formatPublicOperationalNote('backend.order.review', 'en')).toBe(
    'Review note',
  );
  expect(formatPublicOperationalNote('backend.order.review', 'zh')).toBe(
    '待人工复核说明',
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

test('formats the allowlisted Account Truth evidence-readiness contract', () => {
  expect(formatPublicCode('canonical_broker_evidence', 'en')).toBe(
    'Canonical broker evidence',
  );
  expect(formatPublicCode('current_position_snapshot', 'zh')).toBe(
    '当前持仓快照',
  );
  expect(
    formatPublicCode(
      'provide_citic_account_truth_evidence_or_reject_source',
      'zh',
    ),
  ).toBe('补充中信账户事实证据或拒绝该来源');
  expect(formatPublicCode('citic_source_follow_up_required', 'en')).toBe(
    'Known CITIC sources still require evidence review',
  );
  expect(formatPublicCode('review_citic_source_query_windows', 'zh')).toBe(
    '逐份复核中信来源的精确查询区间',
  );
  expect(formatPublicCode('reviewed_query_window_for_source', 'en')).toBe(
    'Reviewed query window for this exact source',
  );
  expect(
    formatPublicCode(
      'citic_source_query_window_review_schema_incomplete',
      'zh',
    ),
  ).toBe('中信查询区间复核 schema 不完整');
  expect(
    formatPublicCode('citic_history_xls_non_financial_activity_ignored', 'zh'),
  ).toBe('已识别指定交易类非资金活动，未生成券商事件');
  expect(formatPublicCode('review_non_financial_activity', 'en')).toBe(
    'Review recognized non-financial designated-trading activity',
  );
  expect(formatPublicCode('versioned_readonly_connector_snapshot', 'en')).toBe(
    'Versioned read-only connector snapshot',
  );
  expect(formatPublicCode('itemized_fill_fees_and_taxes', 'zh')).toBe(
    '逐项成交费用与税',
  );
  expect(formatPublicCode('reviewed_account_and_period_scope', 'zh')).toBe(
    '已复核账户与时段范围',
  );
  expect(
    formatPublicCode('account_truth_coverage_window_undeclared', 'en'),
  ).toBe('No reviewed coverage period is recorded for this broker evidence');
  expect(
    formatPublicCode(
      'bind_account_truth_evidence_to_reviewed_account_scope',
      'zh',
    ),
  ).toBe('将证据绑定到已复核账户范围');
  expect(
    formatPublicCode('review_account_truth_asset_scope_completeness', 'en'),
  ).toBe('Review whether every account asset class is covered');
  expect(
    formatPublicCode('account_truth_evidence_scope_review_revoked', 'zh'),
  ).toBe('已复核证据范围已经撤销');
});

test('formats persisted CITIC scan and query-window integrity blockers', () => {
  expect(formatPublicCode('citic_source_intake_scan_truncated', 'en')).toBe(
    'CITIC source-review scan reached its safety limit',
  );
  expect(formatPublicCode('review_citic_source_intake_scan_limit', 'zh')).toBe(
    '复核中信来源扫描上限并恢复完整计数',
  );
  expect(formatPublicCode('complete_citic_source_intake_scan', 'en')).toBe(
    'Complete CITIC source-review scan',
  );
  expect(
    formatPublicCode('contiguous_non_overlapping_reviewed_query_windows', 'zh'),
  ).toBe('连续且不重叠的已复核查询区间');
  expect(formatPublicCode('citic_query_window_batch_calendar_gap', 'zh')).toBe(
    '已复核查询区间之间存在日期缺口',
  );
});

test('names daily financial preflight blockers without exposing private facts', () => {
  expect(formatPublicCode('account_truth_not_bound_to_plan_date', 'zh')).toBe(
    '账户事实未绑定到当日运行日期',
  );
  expect(formatPublicCode('reviewed_fee_schedule_review_missing', 'zh')).toBe(
    '缺少真实费用方案复核记录',
  );
  expect(
    formatPublicCode('daily_candidate_strategy_candidate_missing', 'en'),
  ).toBe('No promoted strategy candidate is available');
  expect(
    formatPublicCode('daily_candidate_background_window_missed', 'en'),
  ).toBe("Today's background decision window was missed");
});

test('formats unknown Chinese snake-case values as generic review labels', () => {
  expect(formatPublicStatus('new_backend_gate_state', 'zh')).toBe('待确认状态');
  expect(formatPublicCode('new_backend_required_action', 'zh')).toBe(
    '待人工复核项',
  );
  expect(formatPublicNote('new_backend_reason_code', 'zh')).toBe(
    '待人工复核说明',
  );
});

test('formats unknown English status and action sentences as Chinese review labels', () => {
  expect(formatPublicStatus('Data source needs operator review.', 'zh')).toBe(
    '待确认状态',
  );
  expect(formatPublicCode('Review broker evidence before action.', 'zh')).toBe(
    '待人工复核项',
  );
});

test('formats unknown English snake-case values as generic review labels', () => {
  expect(formatPublicStatus('new_backend_gate_state', 'en')).toBe(
    'Status needs review',
  );
  expect(formatPublicCode('new_backend_required_action', 'en')).toBe(
    'Review item',
  );
  expect(formatPublicNote('new_backend_reason_code', 'en')).toBe('Review note');
});

test('formats unknown dotted backend codes as generic labels without hiding normal notes', () => {
  expect(formatPublicStatus('backend.order.review', 'en')).toBe(
    'Status needs review',
  );
  expect(formatPublicCode('backend.order.review', 'zh')).toBe('待人工复核项');
  expect(formatPublicNote('backend.order.review', 'zh')).toBe('待人工复核说明');
  expect(formatPublicNote('Review this manually.', 'en')).toBe(
    'Review this manually.',
  );
  expect(formatPublicNote('Review this manually.', 'zh')).toBe(
    '待人工复核说明',
  );
});

test('formats known audit event codes with specific public labels', () => {
  expect(formatPublicCode('signal.review.recorded', 'zh')).toBe(
    '信号复核已记录',
  );
  expect(formatPublicCode('task.action.status_changed', 'zh')).toBe(
    '动作任务状态已更新',
  );
  expect(formatPublicCode('order.status_changed', 'zh')).toBe('订单状态已更新');
  expect(formatPublicCode('order.fill.recorded', 'zh')).toBe('成交已记录');
  expect(formatPublicCode('order.shadow_divergence_reviewed', 'en')).toBe(
    'Simulation divergence review recorded',
  );
});

test('formats research limitation notes for Chinese user-facing surfaces', () => {
  expect(
    formatPublicNote(
      'Validation evidence is not investment advice or a profitability guarantee.',
      'zh',
    ),
  ).toBe('验证证据不构成投资建议，也不保证收益。');
});

test('formats partial broker position snapshot coverage', () => {
  expect(
    formatPublicNote('account_truth.position_snapshot_scope_incomplete', 'zh'),
  ).toBe('券商持仓快照仅覆盖部分资产类别；其他平台持仓仍待补充证据。');
});

test('formats strategy assignment and simulation notes as user-readable Chinese', () => {
  expect(
    formatPublicNote(
      'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
      'zh',
    ),
  ).toBe(
    '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
  );

  expect(
    formatPublicNote('Requires paper/shadow review before promotion.', 'zh'),
  ).toBe('进入人工复核前，需要完成模拟复核。');
  expect(
    formatPublicNote(
      'Candidate actions should be compared against paper/shadow evidence.',
      'zh',
    ),
  ).toBe('候选动作需要先和模拟复核证据对比。');
  expect(
    formatPublicNote(
      'Candidate actions should be compared against paper/shadow evidence.',
      'en',
    ),
  ).toBe('Candidate actions should be compared with simulation evidence.');
  expect(
    formatPublicNote(
      'Preview evidence is not production attribution evidence.',
      'zh',
    ),
  ).toBe('当前只是预览证据，还不是可用于正式归因的生产证据。');
  expect(
    formatPublicNote(
      'Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.',
      'zh',
    ),
  ).toBe('只有信号、复核、订单和成交事实全部关联后，才允许计算策略收益。');
  expect(formatPublicCode('paper_shadow_evidence', 'zh')).toBe('模拟复核证据');
  expect(formatPublicCode('review_paper_shadow_evidence', 'zh')).toBe(
    '查看模拟复核证据',
  );
  expect(formatPublicCode('paper_shadow_review', 'zh')).toBe('模拟复核');
  expect(formatPublicStatus('shadow_review', 'zh')).toBe('模拟复核');
  expect(
    formatPublicNote('Requires paper/shadow review before promotion.', 'zh'),
  ).not.toContain('模拟复盘');
});

test('formats strategy review statuses without exposing backend promotion codes', () => {
  expect(formatPublicStatus('promotable_for_paper_review', 'en')).toBe(
    'Ready for simulation review',
  );
  expect(formatPublicStatus('promotable_for_paper_review', 'zh')).toBe(
    '可进入模拟复核',
  );
  expect(formatPublicStatus('not_promotable', 'en')).toBe(
    'Not ready for review',
  );
  expect(formatPublicStatus('not_promotable', 'zh')).toBe('暂不满足复核条件');
  expect(formatPublicStatus('not_evaluated', 'zh')).toBe('尚未完成复核评估');
});

test('formats internal evidence references as public audit labels', () => {
  const paperShadowOrder =
    'paper_shadow_order:paper-shadow-preview:dual_ma:600002:buy:100:29.17';
  const paperShadowFill =
    'paper_shadow_fill:paper-shadow-preview:dual_ma:600002:buy:100:29.17:fill:1';
  const datasetSnapshot = 'dataset_snapshot:sha256:preview-dataset';

  expect(formatPublicEvidenceReference(paperShadowOrder, 'zh')).toBe(
    '模拟复核订单 · 29.17',
  );
  expect(formatPublicEvidenceReference(paperShadowFill, 'zh')).toBe(
    '模拟复核成交 · 1',
  );
  expect(formatPublicEvidenceReference(datasetSnapshot, 'zh')).toBe(
    '数据快照 · preview-dataset',
  );
  expect(formatPublicEvidenceReference('strategy:dual_ma', 'en')).toBe(
    'Strategy · dual_ma',
  );
  expect(formatPublicEvidenceReference('strategy:dual_ma', 'zh')).toBe(
    '策略 · dual_ma',
  );
  expect(formatPublicEvidenceReference('paper_order:SHADOW-1', 'en')).toBe(
    'Simulation review order · SHADOW-1',
  );
  expect(formatPublicEvidenceReference('paper_fill:FILL-1', 'zh')).toBe(
    '模拟复核成交 · FILL-1',
  );
  expect(
    formatPublicEvidenceReference(
      'oms_transition:SHADOW-1:4:partially_filled',
      'en',
    ),
  ).toBe('OMS transition · SHADOW-1 #4 Partially Filled');
  expect(
    formatPublicEvidenceReference('oms_transition:SHADOW-1:4:filled', 'zh'),
  ).toBe('OMS 状态变更 · SHADOW-1 #4 已成交');

  const formattedOrder = formatPublicEvidenceReference(paperShadowOrder, 'zh');
  expect(formattedOrder).not.toContain('paper_shadow_order');
  expect(formattedOrder).not.toContain('paper-shadow-preview');
  expect(formattedOrder).not.toContain('dual_ma');
});

test('formats manual review actions as user actions instead of status nouns', () => {
  expect(formatPublicReviewActionLabel('accepted', 'en')).toBe('Mark accepted');
  expect(formatPublicReviewActionLabel('known_difference', 'en')).toBe(
    'Mark known difference',
  );
  expect(formatPublicReviewActionLabel('ledger_candidate', 'en')).toBe(
    'Create ledger candidate',
  );
  expect(formatPublicReviewActionLabel('known_difference', 'zh')).toBe(
    '标记为已知差异',
  );
  expect(formatPublicReviewActionLabel('ledger_candidate', 'zh')).toBe(
    '列为账本修正候选',
  );
  expect(formatPublicStatus('ledger_candidate', 'zh')).toBe('账本修正候选');
});

test('formats account-truth evidence limitations without backend wording', () => {
  expect(
    formatPublicNote(
      'Account Truth review requires staged broker evidence before trusted use.',
      'zh',
    ),
  ).toBe('需要先暂存券商证据并完成复核，才能把账户事实用于决策。');
  expect(
    formatPublicNote('Unresolved reconciliation items require review.', 'zh'),
  ).toBe('仍有对账差异需要人工复核。');

  expect(
    formatPublicNote(
      'Account Truth review requires staged broker evidence before trusted use.',
      'en',
    ),
  ).toBe(
    'Stage broker evidence and review it before account facts are used in decisions.',
  );
  expect(
    formatPublicNote('Unresolved reconciliation items require review.', 'en'),
  ).toBe('Unresolved reconciliation differences need manual review.');
});
