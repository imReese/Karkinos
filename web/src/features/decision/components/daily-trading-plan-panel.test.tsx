import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CopyContext } from '../../../shared/i18n/context';
import { PreferencesContext } from '../../../shared/preferences/context';
import { copy } from '../../../app/copy';
import { DailyTradingPlanPanel } from './daily-trading-plan-panel';
import type { DailyTradingPlanResponse } from '../api';

function TestWrapper({ children }: { children: React.ReactNode }) {
  return (
    <PreferencesContext.Provider
      value={{
        locale: 'en',
        setLocale: vi.fn(),
        theme: 'system',
        resolvedTheme: 'light',
        setTheme: vi.fn(),
      }}
    >
      <CopyContext.Provider value={copy.en}>{children}</CopyContext.Provider>
    </PreferencesContext.Provider>
  );
}

const samplePlan: DailyTradingPlanResponse = {
  schema_version: 'karkinos.daily_trading_plan.v1',
  plan_date: '2026-06-12',
  generated_at: '2026-06-12T09:31:00+08:00',
  source_decision: 'buy',
  conclusion_status: 'manual_confirmation_ready',
  primary_target: 'trading',
  candidate_pool_count: 2,
  manual_ready_count: 2,
  order_intent_count: 2,
  blocked_count: 0,
  available_cash: 100000,
  total_equity: 200000,
  default_execution_mode: 'manual_confirmation',
  broker_bridge_status: 'disabled',
  order_intents: [
    {
      action_id: 1,
      symbol: '600519',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.25,
      estimated_price: 1500,
      estimated_quantity: 20,
      quantity_basis: 'target_weight_lot_rounded',
      estimated_gross_amount: 30000,
      estimated_total_fee: 15,
      estimated_net_cash_impact: -30015,
      available_cash_before: 100000,
      available_cash_after: 69985,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [
        {
          id: 'trading_unit',
          status: 'pass',
          target: 'market',
        },
      ],
      position_effect: {
        current_quantity: 10,
        current_avg_cost: 1400,
        current_market_value: 15000,
        estimated_quantity_after: 30,
        estimated_avg_cost_after: 1466.67,
        cost_basis_method: 'weighted_average_preview',
      },
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready_for_manual_confirmation',
      submission_status: 'manual_confirmation_required',
      does_not_submit_broker_order: true,
      evidence_refs: [],
    },
    {
      action_id: 2,
      symbol: '000858',
      asset_class: 'stock',
      side: 'sell',
      target_weight: 0.05,
      estimated_price: 150,
      estimated_quantity: 100,
      quantity_basis: 'target_weight_lot_rounded',
      estimated_gross_amount: 15000,
      estimated_total_fee: 18,
      estimated_net_cash_impact: 14982,
      available_cash_before: 69985,
      available_cash_after: 84967,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [],
      position_effect: {
        current_quantity: 200,
        current_avg_cost: 140,
        current_market_value: 30000,
        estimated_quantity_after: 100,
        estimated_avg_cost_after: 140,
        cost_basis_method: 'weighted_average_preview',
      },
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'ready_for_manual_confirmation',
      submission_status: 'manual_confirmation_required',
      does_not_submit_broker_order: true,
      evidence_refs: [],
    },
  ],
  blockers: [],
  limitations: [],
};

describe('DailyTradingPlanPanel', () => {
  it('renders allocation delta view with current vs target quantities, weights, and market values', () => {
    render(
      <TestWrapper>
        <DailyTradingPlanPanel
          plan={samplePlan}
          candidates={[]}
          operationsToday={undefined}
          loading={false}
          error={false}
          onRunPaperShadow={vi.fn()}
          paperShadowRunPending={false}
          paperShadowRunError={false}
        />
      </TestWrapper>,
    );

    const panel = screen.getByTestId('decision-daily-trading-plan');
    expect(panel).toBeTruthy();

    // Verify both symbols are rendered
    expect(within(panel).getByText(/600519/)).toBeTruthy();
    expect(within(panel).getByText(/000858/)).toBeTruthy();

    // Verify Allocation Delta section header
    expect(
      within(panel).getAllByText(
        /Current vs target allocation|当前持仓 vs 目标调仓对比/i,
      ).length,
    ).toBeGreaterThan(0);

    // Verify quantity delta indicators
    expect(within(panel).getByText(/10 → 30/)).toBeTruthy();
    expect(within(panel).getByText(/\+20/)).toBeTruthy();
    expect(within(panel).getByText(/200 → 100/)).toBeTruthy();
    expect(within(panel).getByText(/-100/)).toBeTruthy();
  });

  it('renders direct execution queue links to /trading', () => {
    render(
      <TestWrapper>
        <DailyTradingPlanPanel
          plan={samplePlan}
          candidates={[]}
          operationsToday={undefined}
          loading={false}
          error={false}
          onRunPaperShadow={vi.fn()}
          paperShadowRunPending={false}
          paperShadowRunError={false}
        />
      </TestWrapper>,
    );

    const panel = screen.getByTestId('decision-daily-trading-plan');
    const tradingLinks = within(panel).getAllByRole('link', {
      name: /Go to execution queue|前往交易执行队列/i,
    });
    expect(tradingLinks.length).toBeGreaterThan(0);
    for (const link of tradingLinks) {
      expect(link.getAttribute('href')).toBe('/trading');
    }
  });
});
