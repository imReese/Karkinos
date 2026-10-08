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
    expect(within(sandbox).getByText(/净现金非负/)).toBeTruthy();
    expect(within(sandbox).getByText(/不判定正式风控/)).toBeTruthy();
    expect(within(sandbox).queryByText('满足前置风控')).toBeNull();
    expect(within(sandbox).queryByText('现金储备充裕')).toBeNull();
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

  it('does not call positive net cash a risk pass when a sale funds an earlier buy', () => {
    const plan = {
      ...mockPlan,
      available_cash: 100,
      order_intents: [
        {
          ...mockPlan.order_intents[0],
          target_weight: 0.1,
          estimated_price: 10,
        },
        {
          ...mockPlan.order_intents[1],
          side: 'sell',
          target_weight: 0,
          estimated_price: 10,
          position_effect: {
            ...mockPlan.order_intents[1].position_effect!,
            current_quantity: 2000,
          },
        },
      ],
    };
    render(
      <PreferencesProvider>
        <TradingPlanWhatIfSandbox plan={plan} />
      </PreferencesProvider>,
    );
    expect(screen.getByText('净现金非负')).toBeTruthy();
    expect(screen.getByText(/顺序融资条件/)).toBeTruthy();
    expect(screen.queryByText('满足前置风控')).toBeNull();
    expect(screen.queryByText('资金充足率状态')).toBeNull();
  });

  it.each([
    ['missing equity', { total_equity: undefined }],
    ['zero equity', { total_equity: 0 }],
    ['negative equity', { total_equity: -1 }],
    ['non-finite equity', { total_equity: Number.POSITIVE_INFINITY }],
    ['missing cash', { available_cash: undefined }],
    ['negative cash', { available_cash: -1 }],
    ['non-finite cash', { available_cash: Number.NaN }],
  ])(
    'shows preparation conditions instead of invented amounts for %s',
    (_name, invalid) => {
      const plan = { ...mockPlan, ...invalid } as DailyTradingPlanResponse;
      render(
        <PreferencesProvider>
          <TradingPlanWhatIfSandbox plan={plan} />
        </PreferencesProvider>,
      );
      expect(screen.getByRole('status').textContent).toContain('无法推演');
      expect(screen.getByRole('status').textContent).toContain('总权益');
      expect(screen.queryByText('假设净现金余额')).toBeNull();
      const rows = screen.getAllByRole('row').slice(1);
      for (const row of rows) {
        const cells = within(row).getAllByRole('cell');
        expect(cells[5].textContent).toBe('—');
        expect(cells[6].textContent).toBe('—');
      }
      expect(
        screen.getByTestId('decision-what-if-sandbox').textContent,
      ).not.toMatch(/NaN|Infinity/);
    },
  );

  it.each([undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    'requires a valid included price (%s) and resumes after excluding that instrument',
    (price) => {
      const plan = {
        ...mockPlan,
        order_intents: [
          { ...mockPlan.order_intents[0], estimated_price: price as number },
          mockPlan.order_intents[1],
        ],
      };
      render(
        <PreferencesProvider>
          <TradingPlanWhatIfSandbox plan={plan} />
        </PreferencesProvider>,
      );
      expect(screen.getByRole('status').textContent).toContain('有效价格');
      expect(screen.queryByText('假设净现金余额')).toBeNull();
      fireEvent.click(screen.getAllByRole('checkbox')[0]);
      expect(screen.queryByRole('status')).toBeNull();
      expect(screen.getByText('假设净现金余额')).toBeTruthy();
      fireEvent.click(screen.getAllByRole('checkbox')[0]);
      expect(screen.getByRole('status').textContent).toContain('无法推演');
    },
  );

  it('keeps zero cash valid and charges no illustrative fee for unchanged holdings', () => {
    const plan = {
      ...mockPlan,
      available_cash: 0,
      order_intents: [{ ...mockPlan.order_intents[0], target_weight: 0 }],
    };
    render(
      <PreferencesProvider>
        <TradingPlanWhatIfSandbox plan={plan} />
      </PreferencesProvider>,
    );
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText('净现金非负')).toBeTruthy();
    expect(screen.queryByText('假设净现金为负')).toBeNull();
  });
});
