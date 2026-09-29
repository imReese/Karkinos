import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import { portfolioZhCopy } from '../copy.zh';
import { RebalanceAlertBanner } from './rebalance-alert-banner';
import type { DailyTradingPlanResponse } from '../portfolio-feature-boundary';

const emptyPlan: DailyTradingPlanResponse = {
  schema_version: 'karkinos.decision.daily_trading_plan.v1',
  plan_date: '2026-06-17',
  generated_at: '2026-06-17T09:00:00Z',
  source_decision: 'hold',
  conclusion_status: 'no_action_required',
  primary_target: 'portfolio',
  candidate_pool_count: 0,
  manual_ready_count: 0,
  order_intent_count: 0,
  blocked_count: 0,
  available_cash: 100000,
  total_equity: 100000,
  default_execution_mode: 'manual',
  broker_bridge_status: 'ready',
  order_intents: [],
  blockers: [],
  limitations: [],
};

const activePlan: DailyTradingPlanResponse = {
  ...emptyPlan,
  candidate_pool_count: 3,
  order_intent_count: 3,
  manual_ready_count: 1,
  order_intents: [
    {
      action_id: 1,
      symbol: '600519',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.2,
      estimated_price: 1600,
      estimated_quantity: 20,
      quantity_basis: 'shares',
      estimated_gross_amount: 32000,
      estimated_total_fee: 10,
      estimated_net_cash_impact: -32010,
      available_cash_before: 100000,
      available_cash_after: 67990,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [],
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'pending_confirmation',
      submission_status: 'pending',
      does_not_submit_broker_order: false,
      evidence_refs: [],
    },
    {
      action_id: 2,
      symbol: '000858',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.15,
      estimated_price: 150,
      estimated_quantity: 200,
      quantity_basis: 'shares',
      estimated_gross_amount: 30000,
      estimated_total_fee: 10,
      estimated_net_cash_impact: -30010,
      available_cash_before: 67990,
      available_cash_after: 37980,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [],
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready',
      submission_status: 'pending',
      does_not_submit_broker_order: false,
      evidence_refs: [],
    },
    {
      action_id: 3,
      symbol: '300750',
      asset_class: 'stock',
      side: 'sell',
      target_weight: 0,
      estimated_price: 230,
      estimated_quantity: 100,
      quantity_basis: 'shares',
      estimated_gross_amount: 23000,
      estimated_total_fee: 10,
      estimated_net_cash_impact: 22990,
      available_cash_before: 37980,
      available_cash_after: 60970,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [],
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready',
      submission_status: 'pending',
      does_not_submit_broker_order: false,
      evidence_refs: [],
    },
  ],
};

describe('RebalanceAlertBanner', () => {
  test('renders nothing when there are no rebalance actions', () => {
    const { container } = render(
      <RebalanceAlertBanner copy={portfolioZhCopy} tradingPlan={emptyPlan} />,
    );

    expect(screen.queryByTestId('portfolio-rebalance-alert-banner')).toBeNull();
    expect(container.firstChild).toBeNull();
  });

  test('renders alert banner with actions count, buy/sell summary, and decision link', () => {
    render(
      <RebalanceAlertBanner copy={portfolioZhCopy} tradingPlan={activePlan} />,
    );

    expect(screen.getByTestId('portfolio-rebalance-alert-banner')).toBeTruthy();
    expect(screen.getByText('今日有 3 项组合调仓建议待执行')).toBeTruthy();
    expect(screen.getByText('买入 2 · 卖出 1')).toBeTruthy();
    expect(screen.getByText('1 笔需人工确认')).toBeTruthy();
    expect(screen.getByText(/预估换手/)).toBeTruthy();

    const decisionLink = screen.getByTestId('rebalance-alert-decision-link');
    expect(decisionLink.getAttribute('href')).toBe('/decision');
    expect(decisionLink.textContent).toContain('前往决策研判');
  });
});
