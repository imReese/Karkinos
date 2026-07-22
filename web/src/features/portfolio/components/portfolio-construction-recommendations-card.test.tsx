import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { PortfolioConstructionRecommendationsCard } from './portfolio-construction-recommendations-card';
import type { PortfolioConstructionRecommendation } from '../api';

beforeEach(() => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

function renderCard(recommendations: PortfolioConstructionRecommendation[]) {
  return render(
    <PreferencesProvider>
      <PortfolioConstructionRecommendationsCard
        recommendations={recommendations}
      />
    </PreferencesProvider>,
  );
}

test('renders blocked construction recommendations as review evidence in Chinese', () => {
  renderCard([
    {
      symbol: '600519',
      name: '贵州茅台',
      asset_class: 'stock',
      direction: 'sell',
      status: 'blocked',
      actionable: false,
      actual_weight: 0.8,
      target_weight: 0.5,
      drift: -0.3,
      account_truth_gate_status: 'blocked',
      risk_gate_status: 'blocked',
      required_actions: [
        'import_and_reconcile_broker_evidence',
        'resolve_account_truth_before_rebalance',
        'review_blocked_risk_gate',
      ],
      rationale:
        '账户事实未通过，组合构建建议只能用于复核，不能作为可执行候选。',
      source_action_task_id: 7,
    },
  ]);

  expect(screen.getByText('组合构建建议')).toBeTruthy();
  expect(screen.getByText('贵州茅台')).toBeTruthy();
  expect(screen.getByText('600519')).toBeTruthy();
  const recommendation = screen.getByTestId(
    'construction-recommendation-600519',
  );
  expect(within(recommendation).getAllByText('阻断')).toHaveLength(3);
  expect(within(recommendation).getByText('实际')).toBeTruthy();
  expect(within(recommendation).getByText('80.00%')).toBeTruthy();
  expect(within(recommendation).getByText('目标')).toBeTruthy();
  expect(within(recommendation).getByText('50.00%')).toBeTruthy();
  expect(within(recommendation).getByText('漂移')).toBeTruthy();
  expect(within(recommendation).getByText('-30.00%')).toBeTruthy();
  expect(within(recommendation).getByText('账户事实')).toBeTruthy();
  expect(within(recommendation).getByText('风控')).toBeTruthy();
  expect(screen.getByText('导入并对账券商证据')).toBeTruthy();
  expect(screen.getByText('先解决账户事实再再平衡')).toBeTruthy();
  expect(screen.getByText('复核被风控阻断的原因')).toBeTruthy();
  expect(screen.queryByText('import_and_reconcile_broker_evidence')).toBeNull();
  expect(
    screen.queryByText('resolve_account_truth_before_rebalance'),
  ).toBeNull();
  expect(screen.queryByText('review_blocked_risk_gate')).toBeNull();
});

test('marks passed construction recommendations as manual-review candidates', () => {
  renderCard([
    {
      symbol: '510300',
      name: '沪深300ETF',
      asset_class: 'etf',
      direction: 'buy',
      status: 'actionable',
      actionable: true,
      actual_weight: 0.2,
      target_weight: 0.3,
      drift: 0.1,
      account_truth_gate_status: 'pass',
      risk_gate_status: 'passed',
      required_actions: [],
      rationale: '账户事实与风控闸门均已通过，组合构建建议可进入人工复核。',
      source_action_task_id: 8,
    },
  ]);

  const card = screen.getByTestId('construction-recommendation-510300');
  expect(within(card).getByText('可进入人工复核')).toBeTruthy();
  expect(within(card).getByText('账户事实')).toBeTruthy();
  expect(within(card).getByText('风控')).toBeTruthy();
  expect(within(card).getAllByText('通过')).toHaveLength(2);
  expect(within(card).getByText('目标')).toBeTruthy();
  expect(within(card).getByText('30.00%')).toBeTruthy();
  expect(screen.queryByText('actionable')).toBeNull();
  expect(screen.queryByText('passed')).toBeNull();
});
