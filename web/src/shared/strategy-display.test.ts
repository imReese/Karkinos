import { expect, test } from 'vitest';

import {
  formatStrategyAuditLabel,
  formatStrategyDisplayName,
} from './strategy-display';

const strategyNames = {
  dual_ma: 'Dual Moving Average',
  bollinger: 'Bollinger Mean Reversion',
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
