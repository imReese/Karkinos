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

test('formats unknown Chinese snake-case values as generic review labels', () => {
  expect(formatPublicStatus('new_backend_gate_state', 'zh')).toBe('待确认状态');
  expect(formatPublicCode('new_backend_required_action', 'zh')).toBe(
    '待人工复核项',
  );
  expect(formatPublicNote('new_backend_reason_code', 'zh')).toBe(
    '待人工复核说明',
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
    '当前只是把策略绑定到研究上下文；只有信号、复核、订单和成交都串起来后，才会计算它带来的收益。',
  );

  expect(
    formatPublicNote('Requires paper/shadow review before promotion.', 'zh'),
  ).toBe('进入人工复核前，需要完成模拟盘复盘。');
  expect(formatPublicCode('paper_shadow_evidence', 'zh')).toBe(
    '模拟盘复核证据',
  );
  expect(formatPublicCode('review_paper_shadow_evidence', 'zh')).toBe(
    '复核模拟盘证据',
  );
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
