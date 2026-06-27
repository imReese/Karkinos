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
