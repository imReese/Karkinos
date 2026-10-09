import { expect, test } from 'vitest';

import {
  formatStrategyAuditLabel,
  formatStrategyDisplayName,
  isShadowStrategy,
} from './strategy-display';

const strategyNames = {
  dual_ma: 'Dual Moving Average',
  bollinger: 'Bollinger Mean Reversion',
};

const zhStrategyNames = {
  dual_ma: '双均线策略',
  bollinger: '布林带均值回归',
};

test('formats strategy display names from localized names before backend metadata', () => {
  expect(
    formatStrategyDisplayName(
      {
        strategy_id: 'dual_ma',
        name: 'dual_ma',
        display_name: 'Dual MA fallback',
      },
      strategyNames,
    ),
  ).toBe('Dual Moving Average');
});

test('keeps strategy ids as secondary audit metadata when a display name exists', () => {
  expect(formatStrategyAuditLabel('dual_ma', strategyNames)).toBe(
    'Dual Moving Average · dual_ma',
  );
  expect(formatStrategyAuditLabel('custom_breakout', strategyNames)).toBe(
    'custom_breakout',
  );
  expect(formatStrategyAuditLabel(null, strategyNames)).toBe('--');
});

test('formats shadow candidate strategy ids with semantic labels', () => {
  expect(
    formatStrategyDisplayName(
      {
        strategy_id:
          'ai_formula_shadow:ai-shadow-candidate-7cc6b1326efe1a4568a49ca5',
      },
      strategyNames,
    ),
  ).toBe('AI Mined Strategy');
  expect(
    formatStrategyDisplayName(
      {
        strategy_id:
          'ai_formula_shadow:ai-shadow-candidate-7cc6b1326efe1a4568a49ca5',
      },
      zhStrategyNames,
    ),
  ).toBe('AI 挖掘策略');
  expect(
    formatStrategyDisplayName(
      {
        strategy_id: 'ai_formula_shadow:candidate-1',
      },
      zhStrategyNames,
    ),
  ).toBe('AI 挖掘策略 1');
  expect(
    formatStrategyDisplayName(
      {
        strategy_id: 'ai_formula_shadow:candidate-2',
      },
      strategyNames,
    ),
  ).toBe('AI Mined Strategy 2');
});

test('identifies shadow strategies accurately', () => {
  expect(
    isShadowStrategy(
      'ai_formula_shadow:ai-shadow-candidate-7cc6b1326efe1a4568a49ca5',
    ),
  ).toBe(true);
  expect(isShadowStrategy('ai-shadow-candidate-1')).toBe(true);
  expect(isShadowStrategy('dual_ma')).toBe(false);
  expect(isShadowStrategy(null)).toBe(false);
});
