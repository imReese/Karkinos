import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { TradingPlanWhatIfSandbox } from './trading-plan-what-if-sandbox';
import type { DailyTradingPlanResponse } from '../api';

const mockPlan: DailyTradingPlanResponse = {
  schema_version: 'karkinos.trading_plan.v1',
  plan_date: '2026-06-01',
  generated_at: '2026-06-01T09:30:00+08:00',
  source_decision: null,
  conclusion_status: 'manual_ready',
  primary_target: 'portfolio',
  candidate_pool_count: 2,
  manual_ready_count: 2,
  order_intent_count: 2,
  blocked_count: 0,
  available_cash: 50000,
  total_equity: 100000,
  default_execution_mode: 'manual_confirmation',
  broker_bridge_status: 'disabled',
  limitations: [],
  blockers: [],
  order_intents: [
    {
      action_id: 101,
      symbol: '510300',
      display_name: '沪深300ETF',
      name: '沪深300ETF',
      asset_class: 'etf',
      side: 'buy',
      target_weight: 0.15,
      estimated_price: 3.85,
      estimated_quantity: 3800,
      quantity_basis: 'target_weight',
      estimated_gross_amount: 14630,
      estimated_total_fee: 5,
      estimated_net_cash_impact: -14635,
      available_cash_before: 50000,
      available_cash_after: 35365,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready_for_manual_confirmation',
      submission_status: 'pending_manual_confirmation',
      does_not_submit_broker_order: true,
      evidence_refs: [],
      constraint_checks: [],
      position_effect: {
        current_quantity: 0,
        current_avg_cost: null,
        current_market_value: 0,
        estimated_quantity_after: 3800,
        estimated_avg_cost_after: 3.85,
        cost_basis_method: 'moving_average',
      },
    },
    {
      action_id: 102,
      symbol: '510500',
      display_name: '中证500ETF',
      name: '中证500ETF',
      asset_class: 'etf',
      side: 'buy',
      target_weight: 0.1,
      estimated_price: 5.6,
      estimated_quantity: 1700,
      quantity_basis: 'target_weight',
      estimated_gross_amount: 9520,
      estimated_total_fee: 5,
      estimated_net_cash_impact: -9525,
      available_cash_before: 35365,
      available_cash_after: 25840,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready_for_manual_confirmation',
      submission_status: 'pending_manual_confirmation',
      does_not_submit_broker_order: true,
      evidence_refs: [],
      constraint_checks: [],
      position_effect: {
        current_quantity: 0,
        current_avg_cost: null,
        current_market_value: 0,
        estimated_quantity_after: 1700,
        estimated_avg_cost_after: 5.6,
        cost_basis_method: 'moving_average',
      },
    },
  ],
};

describe('TradingPlanWhatIfSandbox', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem('karkinos.locale', 'zh');
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });
  it('renders simulation metrics and candidates table', () => {
    render(
      <PreferencesProvider>
        <TradingPlanWhatIfSandbox plan={mockPlan} />
      </PreferencesProvider>,
    );

    const sandbox = screen.getByTestId('decision-what-if-sandbox');
    expect(sandbox).toBeTruthy();

    expect(within(sandbox).getByText(/调仓推演沙盘/)).toBeTruthy();
    expect(within(sandbox).getByText(/510300/)).toBeTruthy();
    expect(within(sandbox).getByText(/510500/)).toBeTruthy();
    expect(
      within(sandbox).getAllByText(/推演双边换手率/).length,
    ).toBeGreaterThan(0);
    expect(within(sandbox).getByText(/现金储备充裕/)).toBeTruthy();
  });

  it('updates simulated values when toggling candidates and allows resetting', () => {
    render(
      <PreferencesProvider>
        <TradingPlanWhatIfSandbox plan={mockPlan} />
      </PreferencesProvider>,
    );

    const sandbox = screen.getByTestId('decision-what-if-sandbox');

    // Find checkbox for 510500
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(2);

    // Toggle off second candidate
    fireEvent.click(checkboxes[1]);

    // Reset button should now be visible
    const resetBtn = within(sandbox).getByText(/重置为模型推荐/);
    expect(resetBtn).toBeTruthy();

    // Click reset
    fireEvent.click(resetBtn);

    // Reset button should disappear
    expect(within(sandbox).queryByText(/重置为模型推荐/)).toBeNull();
  });
});
