import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { DecisionResponse } from '../api';
import { DecisionCockpitPage } from './decision-cockpit-page';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const dailyDecision: DecisionResponse = {
  lane: 'daily',
  decision_date: '2026-06-12',
  generated_at: '2026-06-12T09:31:00+08:00',
  decision: 'buy',
  requires_manual_confirmation: true,
  summary: {
    candidate_count: 1,
    risk_blocked_count: 0,
    ready_for_manual_confirmation_count: 1,
    portfolio: {
      status: 'available',
      cash: 12000,
      position_count: 2,
      symbols: ['600519', '510300'],
      total_market_value: 28000,
      total_equity: 40000,
    },
    market_data: {
      source_health: 'partial',
      quote_count: 2,
      live_quote_count: 1,
      stale_quote_count: 1,
      missing_symbols: [],
      latest_quote_timestamp: '2026-06-12T09:30:00+08:00',
      has_persistent_cache: true,
    },
    action_tasks: {
      total_count: 1,
      pending_count: 1,
      deferred_count: 0,
      symbols: ['600519'],
    },
    audit: {
      signal_count: 1,
      journal_entry_count: 1,
      risk_checked_count: 1,
      risk_blocked_count: 0,
    },
    account_truth: {
      gate_status: 'pass',
      score: 98,
      has_evidence: true,
      unresolved_mismatch_count: 0,
      required_actions: [],
      blocking_reasons: [],
      limitations: [],
      components: {
        cash: { status: 'pass' },
        position: { status: 'pass' },
        fee: { status: 'pass' },
        cost_basis: { status: 'pass' },
      },
    },
  },
  candidates: [
    {
      action_id: 9,
      action: 'buy',
      symbol: '600519',
      display_name: '贵州茅台',
      asset_class: 'stock',
      title: 'Increase 600519',
      detail:
        '双均线策略触发目标权重 20%，需要人工确认；这是一段很长的中文证据说明，用来验证窄屏和浏览器 125% 缩放时不会把候选动作卡片从右侧裁掉。',
      urgency: 'high',
      target_weight: 0.2,
      price: 123.45,
      risk_gate_status: 'passed',
      manual_confirmation_required: true,
      manual_confirmation_status: 'ready_for_manual_confirmation',
      evidence: {
        strategy: { strategy_id: 'dual_ma' },
        signal: {
          id: 1,
          timestamp: '2026-06-12T09:30:00+08:00',
          strategy_id: 'dual_ma',
          symbol: '600519',
          display_name: '贵州茅台',
          target_weight: 0.2,
        },
        risk_gate: {
          status: 'passed',
          decision_id: 'RISK-1',
          passed: true,
          severity: 'info',
          reasons: [],
        },
        after_cost_oos_validation: {
          status: 'attached',
          strategy_id: 'dual_ma',
          backtest_result_id: 101,
          has_after_cost_report: true,
          has_out_of_sample_validation: true,
          missing_requirements: [],
          after_cost: { net_return: 0.08 },
          oos_validation: { validation_status: 'passed' },
          cost_summary: { commission: 12.3, slippage: 4.5 },
          limitations: ['Backtest evidence is not a profitability claim.'],
        },
        data_freshness: {
          status: 'live',
          quote_timestamp: '2026-06-12T09:30:00+08:00',
          quote_source: 'fixture',
          price: 123.45,
        },
        manual_confirmation: {
          required: true,
          status: 'ready_for_manual_confirmation',
          reason: 'Risk gate passed; operator confirmation is still required.',
        },
        journal: {
          has_journal_entry: true,
          latest_event_type: 'risk.signal.recorded',
          latest_event_source: 'risk_decisions',
          latest_event_ref: 'RISK-1',
        },
        account_truth: {
          gate_status: 'pass',
          score: 98,
          has_evidence: true,
          unresolved_mismatch_count: 0,
          required_actions: [],
          blocking_reasons: [],
          limitations: [],
          components: {
            cash: { status: 'pass' },
            position: { status: 'pass' },
            fee: { status: 'pass' },
            cost_basis: { status: 'pass' },
          },
        },
        paper_shadow: {
          status: 'review_required',
          has_evidence: false,
          required_actions: ['review_paper_shadow_evidence'],
          blocking_reasons: [
            'paper_shadow_evidence_required_before_manual_confirmation',
          ],
        },
        cost_impact: {
          status: 'estimated_from_research_costs',
          source: 'after_cost_oos_validation',
          total_commission: 12.3,
          total_slippage: 4.5,
          cost_summary: { commission: 12.3, slippage: 4.5 },
        },
        uncertainty: {
          status: 'review_required',
          factors: [
            'Backtest evidence is not a profitability claim.',
            'review_paper_shadow_evidence',
          ],
        },
      },
    },
  ],
  no_action_reasons: [],
  limitations: ['Decision platform output is research and portfolio evidence.'],
};

const intradayDecision: DecisionResponse = {
  ...dailyDecision,
  lane: 'intraday',
  decision: 'no_action',
  requires_manual_confirmation: false,
  summary: {
    ...dailyDecision.summary,
    candidate_count: 0,
    ready_for_manual_confirmation_count: 0,
    excluded_daily_count: 1,
  },
  candidates: [],
  excluded_daily_symbols: ['019999'],
  no_action_reasons: ['no_intraday_stock_or_etf_action_tasks'],
};

function installDecisionFetchMock({
  todayResponse = dailyDecision,
  intradayResponse = intradayDecision,
  tradingPlanResponse = {
    schema_version: 'karkinos.daily_trading_plan.v1',
    plan_date: '2026-06-12',
    generated_at: '2026-06-12T09:31:00+08:00',
    source_decision: 'buy',
    conclusion_status: 'manual_confirmation_ready',
    primary_target: 'trading',
    candidate_pool_count: 1,
    manual_ready_count: 1,
    order_intent_count: 1,
    blocked_count: 0,
    available_cash: 100000,
    total_equity: 40000,
    default_execution_mode: 'manual_confirmation',
    broker_bridge_status: 'disabled',
    order_intents: [
      {
        action_id: 9,
        symbol: '600519',
        asset_class: 'stock',
        side: 'buy',
        target_weight: 0.2,
        estimated_price: 123.45,
        estimated_quantity: 600,
        quantity_basis: 'target_weight_total_equity_lot_rounded',
        estimated_gross_amount: 74070,
        estimated_total_fee: 12.3,
        estimated_net_cash_impact: -74082.3,
        available_cash_before: 100000,
        available_cash_after: 25917.7,
        cash_status: 'sufficient',
        cash_shortfall: 0,
        constraint_checks: [
          {
            id: 'trading_unit',
            status: 'pass',
            target: 'market',
          },
          {
            id: 'cash_buffer',
            status: 'pass',
            target: 'portfolio',
          },
          {
            id: 'fee_tax_preview',
            status: 'pass',
            target: 'cost',
          },
        ],
        position_effect: {
          current_quantity: 200,
          current_avg_cost: 100,
          current_market_value: 24690,
          estimated_quantity_after: 800,
          estimated_avg_cost_after: 117.5875,
          cost_basis_method: 'weighted_average_preview',
        },
        fee_breakdown: {
          commission: '11.11',
          stamp_tax: '0',
          transfer_fee: '0.740700',
          other_fees: '0',
          total_fee: '11.85',
        },
        risk_gate_status: 'passed',
        manual_confirmation_status: 'ready_for_manual_confirmation',
        submission_status: 'manual_confirmation_required',
        does_not_submit_broker_order: true,
        evidence_refs: ['decision_action:9', 'strategy:dual_ma'],
      },
    ],
    blockers: [],
    limitations: [
      'Order intents are manual-confirmation previews, not broker submissions.',
    ],
  },
  operationsTodayResponse = {
    schema_version: 'karkinos.operations_today.v1',
    operations_date: '2026-06-12',
    generated_at: '2026-06-12T09:32:00+08:00',
    conclusion_status: 'manual_action_required',
    primary_target: 'paper-shadow',
    health: {
      total: 8,
      pass: 5,
      degraded: 0,
      blocked: 0,
      manual_action_required: 2,
      skipped: 1,
    },
    subsystems: [
      {
        id: 'paper_shadow',
        status: 'manual_action_required',
        tone: 'warning',
        target: 'paper-shadow',
        last_run_at: null,
        next_action: 'review_shadow_divergence',
        limitations: [],
        detail_status: 'review_required',
      },
    ],
    daily_plan: {
      candidate_pool_count: 1,
      manual_ready_count: 1,
      blocked_count: 0,
      order_intent_count: 1,
      conclusion_status: 'manual_confirmation_ready',
    },
    paper_shadow: {
      status: 'review_required',
      run_id: 'shadow:2026-06-12',
      order_intent_count: 1,
      simulated_order_count: 1,
      simulated_fill_count: 1,
      divergence_reviewed_count: 0,
      divergence_status: 'review_required',
      next_manual_review_step: 'review_shadow_divergence',
      last_run_at: '2026-06-12T09:32:00+08:00',
      orders: [
        {
          order_id: 'SHADOW-2026-06-12-9',
          symbol: '600519',
          status: 'shadow_recorded',
          divergence_status: null,
        },
      ],
    },
    limitations: [],
  },
  signalActionDetail = 'Risk gate passed; prepare a manual order only if approved.',
  signalActionsResponse = [
    {
      id: 9,
      source_signal_id: 1,
      symbol: '600519',
      display_name: '贵州茅台',
      title: 'Increase 600519',
      detail: signalActionDetail,
      direction: 'buy',
      urgency: 'high',
      target_weight: 0.2,
      price: 123.45,
      strategy_id: 'dual_ma',
      timestamp: '2026-06-12T09:31:00+08:00',
      asset_class: 'stock',
      status: 'pending',
      risk_decision_id: 'RISK-1',
      risk_gate_passed: true,
      risk_gate_status: 'passed',
      risk_gate_severity: 'info',
      risk_gate_reasons: [],
      manual_confirmation_required: true,
      manual_confirmation_status: 'ready_for_manual_confirmation',
      manual_confirmation_reason: 'Risk gate passed.',
    },
  ],
  journalSourceRef = 'RISK-1',
}: {
  todayResponse?: DecisionResponse;
  intradayResponse?: DecisionResponse;
  tradingPlanResponse?: unknown;
  operationsTodayResponse?: unknown;
  signalActionDetail?: string;
  signalActionsResponse?: unknown;
  journalSourceRef?: string | null;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/decision/today')) {
        return jsonResponse(todayResponse);
      }
      if (url.includes('/api/decision/intraday')) {
        return jsonResponse(intradayResponse);
      }
      if (url.includes('/api/decision/trading-plan')) {
        return jsonResponse(tradingPlanResponse);
      }
      if (url.includes('/api/operations/today')) {
        return jsonResponse(operationsTodayResponse);
      }
      if (url.includes('/api/signals/actions')) {
        return jsonResponse(signalActionsResponse);
      }
      if (url.includes('/api/signals/journal')) {
        return jsonResponse([
          {
            signal: {
              id: 1,
              timestamp: '2026-06-12T09:30:00+08:00',
              strategy_id: 'dual_ma',
              symbol: '600519',
              display_name: '贵州茅台',
              direction: 'buy',
              target_weight: 0.2,
              price: 123.45,
              asset_class: 'stock',
            },
            action_task: null,
            risk_decision: null,
            review: null,
            latest_event: {
              event_type: 'risk.signal.recorded',
              timestamp: '2026-06-12T09:31:00+08:00',
              source: 'risk_decisions',
              source_ref: journalSourceRef,
            },
          },
        ]);
      }
      if (url.includes('/api/trading/actions/9/manual-order')) {
        return jsonResponse({
          order_id: 'manual-order-9',
          status: 'pending_confirm',
        });
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

type RenderDecisionOptions = Parameters<typeof installDecisionFetchMock>[0] & {
  locale?: 'en' | 'zh';
};

function renderDecisionCockpit(options?: RenderDecisionOptions) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const { locale: _locale, ...fetchOptions } = options ?? {};
  const fetchMock = installDecisionFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <DecisionCockpitPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function contributionDecision(): DecisionResponse {
  return {
    ...dailyDecision,
    summary: {
      ...dailyDecision.summary,
      strategy_attribution: {
        gate_status: 'pass',
        strategy_id: 'dual_ma',
        assignment_status: 'active',
        attribution_status: 'complete',
        contribution_status: 'estimated_from_linked_fills',
        has_evidence: true,
        linked_fill_count: 2,
        net_contribution: 129.5,
        gross_realized_pnl: 8,
        gross_unrealized_pnl: 128.5,
        total_commission: 5,
        total_slippage: 1.5,
        total_tax: 0.5,
        manual_unattributed_pnl: 12,
        cash_flow_pnl: 3,
        unattributed_account_pnl: 4,
        required_actions: [],
        blocking_reasons: [],
        limitations: [],
      },
    },
  } as DecisionResponse;
}

test('renders read-only daily trading plan order intent preview', async () => {
  renderDecisionCockpit({ locale: 'en' });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Daily trading plan');
  expect(plan.textContent).toContain('Manual confirmation ready');
  expect(plan.textContent).toContain('Order intent previews');
  expect(plan.textContent).toContain('600519');
  expect(plan.textContent).toContain('600');
  expect(plan.textContent).toContain('Position after');
  expect(plan.textContent).toContain('800');
  expect(plan.textContent).toContain('Cost basis');
  expect(plan.textContent).toContain('Constraint checks');
  expect(plan.textContent).toContain('Trading unit');
  expect(plan.textContent).toContain('Cash buffer');
  expect(plan.textContent).toContain('-¥74,082.30');
  expect(plan.textContent).toContain('Does not submit broker orders');
  expect(plan.textContent).toContain('Paper/shadow simulation review');
  expect(plan.textContent).toContain('Review required');
  expect(plan.textContent).toContain('Review paper/shadow divergence evidence');
  expect(plan.textContent).toContain('Sim orders');
  expect(plan.textContent).toContain('Sim fills');
  expect(plan.textContent).toContain('Divergence reviews');
});

test('renders cash shortfall in daily trading plan without manual readiness', async () => {
  renderDecisionCockpit({
    locale: 'en',
    tradingPlanResponse: {
      schema_version: 'karkinos.daily_trading_plan.v1',
      plan_date: '2026-06-12',
      generated_at: '2026-06-12T09:31:00+08:00',
      source_decision: 'buy',
      conclusion_status: 'cash_shortfall',
      primary_target: 'portfolio',
      candidate_pool_count: 1,
      manual_ready_count: 0,
      order_intent_count: 1,
      blocked_count: 1,
      available_cash: 1000,
      total_equity: 50000,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      order_intents: [
        {
          action_id: 9,
          symbol: '600519',
          asset_class: 'stock',
          side: 'buy',
          target_weight: 0.2,
          estimated_price: 10,
          estimated_quantity: 1000,
          quantity_basis: 'target_weight_total_equity_lot_rounded',
          estimated_gross_amount: 10000,
          estimated_total_fee: 5.1,
          estimated_net_cash_impact: -10005.1,
          available_cash_before: 1000,
          available_cash_after: -9005.1,
          cash_status: 'insufficient_cash',
          cash_shortfall: 9005.1,
          constraint_checks: [
            {
              id: 'cash_buffer',
              status: 'blocked',
              target: 'portfolio',
              cash_buffer_shortfall: 9005.1,
            },
          ],
          fee_breakdown: {
            commission: '5.00',
            transfer_fee: '0.100000',
            total_fee: '5.10',
          },
          risk_gate_status: 'passed',
          manual_confirmation_status: 'ready_for_manual_confirmation',
          submission_status: 'blocked_by_cash_shortfall',
          does_not_submit_broker_order: true,
          evidence_refs: ['decision_action:9', 'strategy:dual_ma'],
        },
      ],
      blockers: [
        {
          action_id: 9,
          symbol: '600519',
          reason: 'insufficient_cash',
          target: 'portfolio',
          risk_gate_status: 'passed',
          manual_confirmation_status: 'ready_for_manual_confirmation',
        },
      ],
      limitations: [
        'Order intents are manual-confirmation previews, not broker submissions.',
      ],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Cash shortfall');
  expect(plan.textContent).toContain(
    '1 candidates · 1 order intent previews · 1 blockers',
  );
  expect(plan.textContent).toContain('¥9,005.10');
  expect(plan.textContent).toContain('Does not submit broker orders');
});

test('renders daily and intraday decision cockpit evidence without execution', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Decision platform')).toBeTruthy();
  expect(await screen.findByText('Decision evidence register')).toBeTruthy();
  expect(
    await screen.findByLabelText('Decision register item: Candidate pool 1'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Manual confirmations 1 ready',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Risk blocks 0 blocked',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Execution default Manual confirmation required',
    ),
  ).toBeTruthy();
  expect((await screen.findAllByText('Daily lane')).length).toBeGreaterThan(0);
  expect((await screen.findAllByText('Intraday lane')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('Decision: Buy')).length).toBeGreaterThan(
    0,
  );
  expect(
    (await screen.findAllByText('贵州茅台 600519')).length,
  ).toBeGreaterThan(0);
  expect(await screen.findByText('Risk gate: Passed')).toBeTruthy();
  expect(
    await screen.findByText('Manual: Ready for manual confirmation'),
  ).toBeTruthy();
  expect(await screen.findByText('After-cost/OOS: Attached')).toBeTruthy();
  expect(await screen.findByText('Data freshness: Live')).toBeTruthy();
  expect(await screen.findByText('Account truth: Pass')).toBeTruthy();
  expect(await screen.findByText('Account truth score: 98')).toBeTruthy();
  expect(await screen.findByText('Journal: Risk signal recorded')).toBeTruthy();
  expect(await screen.findByText('Signal action queue')).toBeTruthy();
  expect(await screen.findByText('Prepare manual order')).toBeTruthy();
  expect(await screen.findByText('Signal journal')).toBeTruthy();
  expect(await screen.findByText('Market health: Partial')).toBeTruthy();
  expect(await screen.findByText('Portfolio equity: ¥40,000.00')).toBeTruthy();
  expect(
    await screen.findByText('No intraday stock or ETF action candidates'),
  ).toBeTruthy();
  expect(
    screen.queryByText('no_intraday_stock_or_etf_action_tasks'),
  ).toBeNull();
  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  expect(
    within(candidateCard)
      .getByRole('link', { name: 'Open Trading approvals: 贵州茅台 600519' })
      .getAttribute('href'),
  ).toBe('/trading');
  const backtestEvidenceHref = within(candidateCard)
    .getByRole('link', { name: 'Open Backtest evidence: 贵州茅台 600519' })
    .getAttribute('href');
  const backtestEvidenceUrl = new URL(
    String(backtestEvidenceHref),
    'http://localhost',
  );
  expect(backtestEvidenceUrl.pathname).toBe('/backtest');
  expect(backtestEvidenceUrl.searchParams.get('symbol')).toBe('600519');
  expect(backtestEvidenceUrl.searchParams.get('assetClass')).toBe('stock');
  expect(backtestEvidenceUrl.searchParams.get('strategy')).toBe('dual_ma');
  expect(
    within(candidateCard)
      .getByRole('link', { name: 'Open holding detail: 贵州茅台 600519' })
      .getAttribute('href'),
  ).toBe('/portfolio/600519');
  expect(screen.queryByText(/automatic execution/i)).toBeNull();
});

test('labels decision candidates as a candidate pool in Chinese', async () => {
  renderDecisionCockpit({ locale: 'zh' });

  expect(await screen.findByText('决策证据登记')).toBeTruthy();
  expect(
    await screen.findByLabelText('Decision register item: 候选池 1'),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain('候选动作 1');
});

test('collapses dense signal action queues until the user asks for details', async () => {
  renderDecisionCockpit({
    locale: 'zh',
    signalActionsResponse: Array.from({ length: 8 }, (_, index) => ({
      id: index + 1,
      source_signal_id: index + 1,
      symbol: `6005${index}`,
      display_name: `测试标的 ${index + 1}`,
      title: `Increase 6005${index}`,
      detail: 'Risk gate passed; prepare a manual order only if approved.',
      direction: 'buy',
      urgency: 'high',
      target_weight: 0.2,
      price: 123.45,
      strategy_id: 'dual_ma',
      timestamp: '2026-06-12T09:31:00+08:00',
      asset_class: 'stock',
      status: 'pending',
      risk_decision_id: `RISK-${index + 1}`,
      risk_gate_passed: true,
      risk_gate_status: 'passed',
      risk_gate_severity: 'info',
      risk_gate_reasons: [],
      manual_confirmation_required: true,
      manual_confirmation_status: 'ready_for_manual_confirmation',
      manual_confirmation_reason: 'Risk gate passed.',
    })),
  });

  const collapsed = await screen.findByTestId('signal-queue-collapsed');
  expect(collapsed.textContent).toContain('8 个信号动作已汇总');
  expect(screen.queryByTestId('signal-action-card-1')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '展开信号动作' }));
  expect(await screen.findByTestId('signal-action-card-1')).toBeTruthy();
});

test('localizes signal journal audit events without exposing dotted event keys', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Signal journal')).toBeTruthy();
  expect(await screen.findByText('Journal: Risk signal recorded')).toBeTruthy();
  expect(await screen.findByText('Risk signal recorded')).toBeTruthy();
  expect(document.body.textContent).not.toContain('risk.signal.recorded');
});

test('links signal journal entries to single-instrument evidence surfaces with public source refs', async () => {
  renderDecisionCockpit({
    journalSourceRef:
      'paper_shadow_order:paper-shadow-preview:dual_ma:600519:buy:100:29.17',
  });

  await screen.findByText('Signal journal');
  const signalJournal = await screen.findByTestId('signal-journal-panel');

  expect(
    within(signalJournal).getByText('Simulation review order · 29.17'),
  ).toBeTruthy();
  expect(signalJournal.textContent).not.toContain('paper_shadow_order');
  expect(signalJournal.textContent).not.toContain('paper-shadow-preview');

  const backtestEvidenceHref = within(signalJournal)
    .getByRole('link', { name: 'Open Backtest evidence: 贵州茅台 600519' })
    .getAttribute('href');
  const backtestEvidenceUrl = new URL(
    String(backtestEvidenceHref),
    'http://localhost',
  );
  expect(backtestEvidenceUrl.pathname).toBe('/backtest');
  expect(backtestEvidenceUrl.searchParams.get('symbol')).toBe('600519');
  expect(backtestEvidenceUrl.searchParams.get('assetClass')).toBe('stock');
  expect(backtestEvidenceUrl.searchParams.get('strategy')).toBe('dual_ma');

  expect(
    within(signalJournal)
      .getByRole('link', { name: 'Open attribution review: 贵州茅台 600519' })
      .getAttribute('href'),
  ).toBe('/portfolio/600519#holding-strategy-attribution-boundary');
});

test('prepares manual orders with public notes instead of internal action ids', async () => {
  const { fetchMock } = renderDecisionCockpit();

  await screen.findByText('Signal action queue');
  fireEvent.click(screen.getByRole('button', { name: 'Prepare manual order' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/actions/9/manual-order',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  const manualOrderCall = fetchMock.mock.calls.find(([input]) =>
    String(input).includes('/api/trading/actions/9/manual-order'),
  );
  expect(manualOrderCall).toBeTruthy();
  const request = manualOrderCall?.[1];
  const body = JSON.parse(String(request?.body ?? '{}')) as {
    note?: string;
  };
  expect(body.note).toBe('Prepared from Decision action queue.');
  expect(body.note).not.toContain('signal action');
  expect(body.note).not.toContain('9');
});

test('links signal action queue cards back to single-instrument evidence surfaces', async () => {
  renderDecisionCockpit();

  await screen.findByText('Signal action queue');
  const signalQueue = await screen.findByTestId('signal-action-card-9');

  const backtestEvidenceHref = within(signalQueue)
    .getByRole('link', { name: 'Open Backtest evidence: 贵州茅台 600519' })
    .getAttribute('href');
  const backtestEvidenceUrl = new URL(
    String(backtestEvidenceHref),
    'http://localhost',
  );
  expect(backtestEvidenceUrl.pathname).toBe('/backtest');
  expect(backtestEvidenceUrl.searchParams.get('symbol')).toBe('600519');
  expect(backtestEvidenceUrl.searchParams.get('assetClass')).toBe('stock');
  expect(backtestEvidenceUrl.searchParams.get('strategy')).toBe('dual_ma');

  expect(
    within(signalQueue)
      .getByRole('link', { name: 'Open attribution review: 贵州茅台 600519' })
      .getAttribute('href'),
  ).toBe('/portfolio/600519#holding-strategy-attribution-boundary');
});

test('surfaces degraded and blocked account-truth gates in decision summaries', async () => {
  const degradedToday = {
    ...dailyDecision,
    summary: {
      ...dailyDecision.summary,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'degraded',
        score: 64,
        unresolved_mismatch_count: 2,
        required_actions: ['review_position_difference'],
        blocking_reasons: [],
        limitations: ['Broker evidence is stale.'],
        components: {
          ...(dailyDecision.summary.account_truth?.components ?? {}),
          position: { status: 'warning' },
        },
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'account_truth_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          account_truth: {
            ...dailyDecision.candidates[0].evidence.account_truth,
            gate_status: 'degraded',
            score: 64,
            unresolved_mismatch_count: 2,
            required_actions: ['review_position_difference'],
            limitations: ['Broker evidence is stale.'],
            components: {
              ...(dailyDecision.candidates[0].evidence.account_truth
                ?.components ?? {}),
              position: { status: 'warning' },
            },
          },
        },
      },
    ],
  };
  const blockedIntraday = {
    ...intradayDecision,
    summary: {
      ...intradayDecision.summary,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'blocked',
        score: 32,
        has_evidence: false,
        unresolved_mismatch_count: 4,
        required_actions: ['import_and_reconcile_broker_evidence'],
        blocking_reasons: ['account_truth_score_unavailable'],
        limitations: ['Account Truth evidence is missing.'],
        components: {
          cash: { status: 'missing' },
          position: { status: 'missing' },
          fee: { status: 'missing' },
          cost_basis: { status: 'missing' },
        },
      },
    },
  };

  renderDecisionCockpit({
    todayResponse: degradedToday,
    intradayResponse: blockedIntraday,
  });

  expect(
    (await screen.findAllByText('Account truth gate')).length,
  ).toBeGreaterThan(0);
  expect((await screen.findAllByText('Degraded · 64')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('Blocked · 32')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText(/2 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/4 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/Review position difference/)).toBeTruthy();
  expect(
    await screen.findByText(/Import broker evidence and run reconciliation/),
  ).toBeTruthy();
  expect(screen.queryByText(/review_position_difference/)).toBeNull();
  expect(screen.queryByText(/import_and_reconcile_broker_evidence/)).toBeNull();
  expect(
    await screen.findByText('Manual: Account truth review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Account truth: Degraded')).toBeTruthy();
});

test('surfaces strategy-attribution gate status in decision summaries', async () => {
  const blockedToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      strategy_attribution: {
        gate_status: 'blocked',
        strategy_id: 'dual_ma',
        assignment_status: 'active',
        attribution_status: 'not_started',
        contribution_status: 'no_linked_fills',
        has_evidence: false,
        required_actions: [
          'link_strategy_signals_orders_fills_and_contribution',
        ],
        blocking_reasons: ['strategy_attribution_not_ready'],
        limitations: [],
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'strategy_attribution_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          strategy_attribution: {
            gate_status: 'blocked',
            strategy_id: 'dual_ma',
            assignment_status: 'active',
            attribution_status: 'not_started',
            contribution_status: 'no_linked_fills',
            has_evidence: false,
            required_actions: [
              'link_strategy_signals_orders_fills_and_contribution',
            ],
            blocking_reasons: ['strategy_attribution_not_ready'],
            limitations: [],
          },
        },
      },
    ],
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: blockedToday });

  expect(
    (await screen.findAllByText('Strategy attribution gate')).length,
  ).toBeGreaterThan(0);
  expect(
    (await screen.findAllByText('Blocked · Dual Moving Average')).length,
  ).toBeGreaterThan(0);
  expect(
    (await screen.findAllByText(/Audit id: dual_ma/)).length,
  ).toBeGreaterThan(0);
  expect(
    screen.queryByText('Blocked · Dual Moving Average · dual_ma'),
  ).toBeNull();
  expect(screen.queryByText('Blocked · dual_ma')).toBeNull();
  expect(
    await screen.findByText(
      /Link strategy signals, reviews, orders, fills, and contribution evidence/,
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(/link_strategy_signals_orders_fills_and_contribution/),
  ).toBeNull();
  expect(
    await screen.findByText('Manual: Strategy attribution review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Strategy attribution: Blocked')).toBeTruthy();
});

test('surfaces strategy contribution components in decision summaries', async () => {
  renderDecisionCockpit({ todayResponse: contributionDecision() });

  expect(
    await screen.findByText(/Contribution status: Estimated from linked fills/),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain(
    'Contribution status: Estimated From Linked Fills',
  );
  expect(document.body.textContent).not.toContain(
    'estimated_from_linked_fills',
  );
  expect(await screen.findByText(/Net contribution: ¥129.50/)).toBeTruthy();
  expect(await screen.findByText(/Gross realized P\/L: ¥8.00/)).toBeTruthy();
  expect(
    await screen.findByText(/Gross unrealized P\/L: ¥128.50/),
  ).toBeTruthy();
  expect(
    await screen.findByText(/Commission \/ slippage: ¥5.00 \/ ¥1.50/),
  ).toBeTruthy();
  expect(
    await screen.findByText(/Manual \/ cash-flow movement: ¥12.00 \/ ¥3.00/),
  ).toBeTruthy();
  expect(
    await screen.findByText(/Tax \/ excluded movement: ¥0.50 \/ ¥4.00/),
  ).toBeTruthy();
});

test('localizes strategy contribution status in decision summaries', async () => {
  renderDecisionCockpit({
    todayResponse: contributionDecision(),
    locale: 'zh',
  });

  expect(await screen.findByText(/贡献状态: 基于已归属成交估算/)).toBeTruthy();
  expect(document.body.textContent).not.toContain(
    'estimated_from_linked_fills',
  );
  expect(document.body.textContent).not.toContain(
    'Estimated From Linked Fills',
  );
});

test('renders localized candidate evidence chain for decision review', async () => {
  renderDecisionCockpit({ locale: 'zh' });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect(card.textContent).toContain('候选动作证据链');
  expect(card.textContent).toContain('策略来源');
  expect(card.textContent).toContain('dual_ma');
  expect(card.textContent).toContain('行情状态');
  expect(card.textContent).toContain('实时行情');
  expect(card.textContent).toContain('账户事实');
  expect(card.textContent).toContain('通过');
  expect(card.textContent).toContain('风控状态');
  expect(card.textContent).toContain('已通过');
  expect(card.textContent).toContain('研究证据');
  expect(card.textContent).toContain('已关联');
  expect(card.textContent).toContain('模拟证据');
  expect(card.textContent).toContain('需要复核');
  expect(card.textContent).toContain('成本影响');
  expect(card.textContent).toContain('¥12.30');
  expect(card.textContent).toContain('¥4.50');
  expect(card.textContent).toContain('不确定性');
  expect(card.textContent).toContain('研究证据不代表收益保证');
  expect(card.textContent).toContain('人工确认');
  expect(card.textContent).not.toContain('review_paper_shadow_evidence');
  expect(card.textContent).not.toContain('estimated_from_research_costs');
});

test('localizes decision action details before rendering the signal queue', async () => {
  renderDecisionCockpit({
    signalActionDetail:
      'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    locale: 'zh',
  });

  expect(
    await screen.findByText(
      '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain(
    'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
  );
});

test('localizes decision candidate details before rendering action cards', async () => {
  renderDecisionCockpit({
    todayResponse: {
      ...dailyDecision,
      candidates: [
        {
          ...dailyDecision.candidates[0],
          detail:
            'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
        },
      ],
    },
    locale: 'zh',
  });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect(
    within(card).getByText(
      '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
    ),
  ).toBeTruthy();
  expect(card.textContent).not.toContain(
    'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
  );
});

test('marks stale data candidates as review-only instead of certain actions', async () => {
  const staleToday = {
    ...dailyDecision,
    decision: 'review_required',
    requires_manual_confirmation: false,
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      market_data: {
        ...dailyDecision.summary.market_data,
        source_health: 'stale',
        live_quote_count: 0,
        stale_quote_count: 1,
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'data_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          data_freshness: {
            ...dailyDecision.candidates[0].evidence.data_freshness,
            status: 'stale',
            stale_reason: 'quote_older_than_expected_session',
          },
          certainty: {
            status: 'degraded',
            posture: 'review_required',
            required_actions: ['refresh_or_confirm_market_data'],
            uncertain_reasons: ['quote_older_than_expected_session'],
          },
        },
      },
    ],
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: staleToday, locale: 'zh' });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect((await screen.findAllByText('决策: 需要复核')).length).toBeGreaterThan(
    0,
  );
  expect(card.textContent).toContain('操作确定性');
  expect(card.textContent).toContain('需要先复核数据或账户事实');
  expect(card.textContent).toContain('刷新或确认行情');
  expect(card.textContent).toContain('行情早于预期交易时段');
  expect(card.textContent).toContain('人工确认: 需要数据复核');
  expect(card.textContent).not.toContain('打开交易审批');
  expect(card.textContent).not.toContain('quote_older_than_expected_session');
});

test('shows localized risk gate reasons on blocked decision candidates', async () => {
  const blockedToday = {
    ...dailyDecision,
    summary: {
      ...dailyDecision.summary,
      risk_blocked_count: 1,
      ready_for_manual_confirmation_count: 0,
    },
    candidates: dailyDecision.candidates.map((candidate) => ({
      ...candidate,
      risk_gate_status: 'blocked',
      manual_confirmation_status: 'blocked',
      evidence: {
        ...candidate.evidence,
        risk_gate: {
          ...candidate.evidence.risk_gate,
          status: 'blocked',
          passed: false,
          severity: 'error',
          reasons: ['risk_gate_blocked', 'new_backend_risk_reason'],
        },
      },
    })),
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: blockedToday, locale: 'zh' });

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  expect(candidateCard.textContent).toContain('风控阻断证据');
  expect(candidateCard.textContent).toContain('风控闸门正在阻断动作');
  expect(candidateCard.textContent).toContain('待人工复核说明');
  expect(candidateCard.textContent).not.toContain('risk_gate_blocked');
  expect(candidateCard.textContent).not.toContain('new_backend_risk_reason');
});

test('localizes no-action, degraded, blocked, and review-required decision states', async () => {
  const localizedToday = {
    ...dailyDecision,
    decision: 'review_required',
    requires_manual_confirmation: false,
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'degraded',
        score: 72,
        unresolved_mismatch_count: 1,
        required_actions: ['review_position_difference'],
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'blocked_by_data_quality',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          data_freshness: {
            ...dailyDecision.candidates[0].evidence.data_freshness,
            status: 'missing',
            reason: 'missing_latest_quote',
          },
          account_truth: {
            ...dailyDecision.candidates[0].evidence.account_truth,
            gate_status: 'degraded',
            score: 72,
            unresolved_mismatch_count: 1,
            required_actions: ['review_position_difference'],
          },
          certainty: {
            status: 'blocked',
            posture: 'blocked',
            required_actions: ['refresh_market_data'],
            uncertain_reasons: [],
          },
        },
      },
    ],
  } as DecisionResponse;
  const localizedIntraday = {
    ...intradayDecision,
    decision: 'no_action',
    no_action_reasons: ['no_intraday_stock_or_etf_action_tasks'],
  } as DecisionResponse;

  renderDecisionCockpit({
    todayResponse: localizedToday,
    intradayResponse: localizedIntraday,
    locale: 'zh',
  });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect((await screen.findAllByText('决策: 需要复核')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('决策: 不操作')).length).toBeGreaterThan(
    0,
  );
  expect(card.textContent).toContain('账户事实: 降级');
  expect(card.textContent).toContain('操作确定性');
  expect(card.textContent).toContain('证据修复前阻断');
  expect(card.textContent).toContain('刷新行情');
  expect(card.textContent).toContain('人工确认: 数据质量阻断');
  expect(await screen.findByText('暂无盘中股票或 ETF 候选动作')).toBeTruthy();
  expect(document.body.textContent).not.toContain('未映射状态');
  expect(document.body.textContent).not.toContain('no_action');
  expect(document.body.textContent).not.toContain('blocked_by_data_quality');
  expect(document.body.textContent).not.toContain(
    'no_intraday_stock_or_etf_action_tasks',
  );
});

test('renders localized decision workflow tasks before candidate actions', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'data_refresh',
          priority: 10,
          status: 'degraded',
          title: 'Data refresh',
          description:
            'Some decision quotes are stale, cached, or only partially available.',
          required_actions: ['refresh_or_confirm_market_data'],
          blocking_reasons: ['market_data_not_fully_live'],
          evidence: { source_health: 'partial' },
        },
        {
          id: 'account_truth',
          priority: 20,
          status: 'blocked',
          title: 'Account truth',
          description:
            'Broker evidence and local account facts are checked before action review.',
          required_actions: ['preview_import_and_reconcile_broker_evidence'],
          blocking_reasons: ['account_truth_score_unavailable'],
          evidence: { gate_status: 'blocked', score: null },
        },
        {
          id: 'risk_review',
          priority: 30,
          status: 'blocked',
          title: 'Risk review',
          description:
            'At least one candidate is blocked by the pre-trade risk gate.',
          required_actions: ['review_risk_blockers'],
          blocking_reasons: ['risk_gate_blocked'],
          evidence: { risk_blocked_count: 1 },
        },
        {
          id: 'strategy_evidence',
          priority: 40,
          status: 'pass',
          title: 'Strategy evidence',
          description:
            'Strategy candidates are reviewed only after data and account facts.',
          required_actions: [],
          blocking_reasons: [],
          evidence: { candidate_count: 1 },
        },
        {
          id: 'paper_shadow_review',
          priority: 50,
          status: 'review_required',
          title: 'Paper/shadow review',
          description:
            'Candidate actions should be compared against paper/shadow evidence.',
          required_actions: ['review_paper_shadow_evidence'],
          blocking_reasons: [],
          evidence: { candidate_count: 1 },
        },
        {
          id: 'manual_confirmation',
          priority: 60,
          status: 'blocked',
          title: 'Manual confirmation',
          description:
            'Manual confirmation is blocked until upstream evidence is resolved.',
          required_actions: ['resolve_upstream_workflow_blockers'],
          blocking_reasons: ['upstream_workflow_blockers'],
          evidence: { candidate_count: 1 },
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'zh' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(await screen.findByText('决策工作流')).toBeTruthy();
  expect(workflow.textContent).toContain(
    '先检查数据和账户事实，再查看策略机会',
  );
  expect(workflow.textContent).toContain('数据刷新');
  expect(workflow.textContent).toContain('刷新或确认行情');
  expect(workflow.textContent).toContain('账户事实');
  expect(workflow.textContent).toContain('预览券商凭证导入并完成对账');
  expect(workflow.textContent).toContain('风险复核');
  expect(workflow.textContent).toContain('策略证据');
  expect(workflow.textContent).toContain('模拟复核');
  expect(workflow.textContent).toContain('人工确认');
  expect(
    screen
      .getByRole('link', { name: '打开行情中心：数据刷新' })
      .getAttribute('href'),
  ).toBe('/market');
  expect(
    screen
      .getByRole('link', { name: '打开风控中心：风险复核' })
      .getAttribute('href'),
  ).toBe('/risk');
  expect(
    screen
      .getByRole('link', { name: '打开回测实验室：策略证据' })
      .getAttribute('href'),
  ).toBe('/backtest');
  expect(
    screen
      .getByRole('link', { name: '打开回测实验室：模拟复核' })
      .getAttribute('href'),
  ).toBe('/backtest');
  expect(
    screen
      .getByRole('link', { name: '打开交易审批：人工确认' })
      .getAttribute('href'),
  ).toBe('/trading');
  expect(workflow.textContent).not.toContain(
    'preview_import_and_reconcile_broker_evidence',
  );
  expect(workflow.textContent).not.toContain('refresh_or_confirm_market_data');
  expect(workflow.textContent).not.toContain('paper_shadow_review');
  expect(workflow.textContent).not.toContain('paper/shadow evidence');
  expect(workflow.textContent).not.toContain('模拟复盘');
  expect(
    workflow.textContent?.indexOf('数据刷新') ?? Number.POSITIVE_INFINITY,
  ).toBeLessThan(workflow.textContent?.indexOf('策略证据') ?? -1);
  expect(
    workflow.textContent?.indexOf('账户事实') ?? Number.POSITIVE_INFINITY,
  ).toBeLessThan(workflow.textContent?.indexOf('策略证据') ?? -1);
});

test('surfaces the one next action before dense decision evidence', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    requires_manual_confirmation: false,
    summary: {
      ...dailyDecision.summary,
      candidate_count: 50,
      ready_for_manual_confirmation_count: 0,
      risk_blocked_count: 0,
      workflow_tasks: [
        {
          id: 'account_truth',
          priority: 20,
          status: 'degraded',
          title: 'Account truth',
          description: 'Account facts need better broker evidence.',
          required_actions: [
            'provide_cash_snapshot',
            'provide_position_snapshot',
          ],
          blocking_reasons: [],
          evidence: { gate_status: 'degraded', score: 85 },
        },
        {
          id: 'risk_review',
          priority: 30,
          status: 'review_required',
          title: 'Risk review',
          description: 'Candidates have not passed the pre-trade risk gate.',
          required_actions: ['run_pre_trade_risk_gate'],
          blocking_reasons: ['risk_gate_not_checked'],
          evidence: { risk_not_checked_count: 50 },
        },
        {
          id: 'manual_confirmation',
          priority: 60,
          status: 'blocked',
          title: 'Manual confirmation',
          description: 'Manual confirmation waits for upstream workflow gates.',
          required_actions: ['resolve_upstream_workflow_blockers'],
          blocking_reasons: ['upstream_workflow_blockers'],
          evidence: { candidate_count: 50 },
        },
      ],
    },
    candidates: dailyDecision.candidates.map((candidate) => ({
      ...candidate,
      risk_gate_status: 'not_checked',
      manual_confirmation_required: false,
      manual_confirmation_status: 'account_truth_review_required',
      evidence: {
        ...candidate.evidence,
        risk_gate: {
          ...candidate.evidence.risk_gate,
          status: 'not_checked',
          decision_id: null,
          passed: null,
          severity: 'warning',
          reasons: ['risk_gate_not_checked'],
        },
        account_truth: {
          gate_status: 'degraded',
          score: 85,
          has_evidence: false,
          unresolved_mismatch_count: 0,
          required_actions: ['provide_cash_snapshot'],
          blocking_reasons: [],
          limitations: [],
        },
      },
    })),
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'zh' });

  const guide = await screen.findByTestId('decision-next-action-guide');
  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(guide.textContent).toContain('下一步');
  expect(guide.textContent).toContain('先运行下单前风控');
  expect(workflow.textContent).toContain('50 个候选：复核顺序明细已收起');
  expect(workflow.textContent).toContain('展开工作流明细');
  expect(guide.textContent).toContain(
    '50 个候选只是候选池；当前 0 个可人工确认。',
  );
  expect(guide.textContent).toContain('候选池不是待下单清单');
  expect(
    within(guide)
      .getByRole('link', { name: '打开风控中心：先运行下单前风控' })
      .getAttribute('href'),
  ).toBe('/risk');
  const collapsedSummary = await screen.findByTestId(
    'decision-summary-collapsed',
  );
  expect(collapsedSummary.textContent).toContain('50 个候选：状态明细已收起');
  expect(screen.queryByTestId('decision-summary-grid')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '展开状态明细' }));
  expect(await screen.findByTestId('decision-summary-grid')).toBeTruthy();
  expect(await screen.findByText('50 个候选已汇总')).toBeTruthy();
  expect(screen.queryByTestId('decision-candidate-card-600519')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '展开证据明细' }));
  expect(
    await screen.findByTestId('decision-candidate-card-600519'),
  ).toBeTruthy();
  expect(
    document.body.textContent?.indexOf('先运行下单前风控') ??
      Number.POSITIVE_INFINITY,
  ).toBeLessThan(document.body.textContent?.indexOf('候选池') ?? -1);
  expect(guide.compareDocumentPosition(workflow)).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});

test('uses generic review labels for unknown decision workflow action codes', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'new_backend_workflow_step',
          priority: 10,
          status: 'new_backend_gate_state',
          title: 'New backend workflow step',
          description: 'A future backend code should not leak into the UI.',
          required_actions: ['new_backend_required_action'],
          blocking_reasons: ['new_backend_blocking_reason'],
          evidence: {},
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'zh' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(workflow.textContent).toContain('待人工复核项');
  expect(workflow.textContent).toContain('待确认状态');
  expect(workflow.textContent).not.toContain('new_backend_required_action');
  expect(workflow.textContent).not.toContain('new_backend_workflow_step');
  expect(workflow.textContent).not.toContain('未映射原因');
  expect(workflow.textContent).not.toContain('未映射状态');
});

test('uses generic review-note labels for unknown decision workflow blocking reasons', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'account_truth',
          priority: 10,
          status: 'blocked',
          title: 'New backend workflow step',
          description: 'A future backend reason should not leak into the UI.',
          required_actions: [],
          blocking_reasons: ['new_backend_blocking_reason'],
          evidence: {},
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'zh' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(workflow.textContent).toContain('待人工复核说明');
  expect(workflow.textContent).not.toContain('待人工复核项');
  expect(workflow.textContent).not.toContain('new_backend_blocking_reason');
  expect(workflow.textContent).not.toContain('未映射原因');
});

test('uses generic English review labels for unknown decision workflow action codes', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'new_backend_workflow_step',
          priority: 10,
          status: 'new_backend_gate_state',
          title: 'New backend workflow step',
          description: 'A future backend code should not leak into the UI.',
          required_actions: ['new_backend_required_action'],
          blocking_reasons: ['new_backend_blocking_reason'],
          evidence: {},
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'en' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(workflow.textContent).toContain('Review item');
  expect(workflow.textContent).toContain('Status needs review');
  expect(workflow.textContent).not.toContain('new_backend_required_action');
  expect(workflow.textContent).not.toContain('New Backend Required Action');
  expect(workflow.textContent).not.toContain('new_backend_workflow_step');
  expect(workflow.textContent).not.toContain('New Backend Workflow Step');
});

test('uses generic English review-note labels for unknown decision workflow blocking reasons', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'account_truth',
          priority: 10,
          status: 'blocked',
          title: 'New backend workflow step',
          description: 'A future backend reason should not leak into the UI.',
          required_actions: [],
          blocking_reasons: ['new_backend_blocking_reason'],
          evidence: {},
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'en' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(workflow.textContent).toContain('Review note');
  expect(workflow.textContent).not.toContain('Review item');
  expect(workflow.textContent).not.toContain('new_backend_blocking_reason');
  expect(workflow.textContent).not.toContain('New Backend Blocking Reason');
});

test('shows strategy display names before internal ids in candidate evidence', async () => {
  renderDecisionCockpit();

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  expect(candidateCard.textContent).toContain('Dual Moving Average');
  expect(candidateCard.textContent).toContain('Audit id');
  expect(candidateCard.textContent).toContain('dual_ma');
  expect(candidateCard.textContent).not.toContain(
    'Dual Moving Average · dual_ma',
  );
  expect(candidateCard.textContent).not.toMatch(/Strategy\s*dual_ma/);
  expect(candidateCard.textContent).not.toMatch(/Strategy source\s*dual_ma/);
});

test('shows instrument names before symbols across decision candidates and signal audit', async () => {
  renderDecisionCockpit({ locale: 'zh' });

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );

  expect(candidateCard.textContent).toContain('贵州茅台');
  expect(candidateCard.textContent).toContain('600519');
  expect(candidateCard.textContent).toContain('贵州茅台 600519');
  expect(candidateCard.textContent).not.toMatch(/^600519\s*买入/u);
  expect(
    (await screen.findAllByText('贵州茅台 600519')).length,
  ).toBeGreaterThan(1);
  expect(document.body.textContent).not.toContain(
    '贵州茅台 600519 · 双均线策略 · dual_ma',
  );
  expect(document.body.textContent).not.toContain('Increase 600519');
});

test('links decision candidates to holding attribution review', async () => {
  renderDecisionCockpit();

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  const attributionLink = within(candidateCard).getByRole('link', {
    name: 'Open attribution review: 贵州茅台 600519',
  });

  expect(attributionLink.getAttribute('href')).toBe(
    '/portfolio/600519#holding-strategy-attribution-boundary',
  );
});

test('keeps decision cockpit candidates accessible on narrow responsive layouts', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Decision platform')).toBeTruthy();

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  const summaryGrid = screen.getByTestId('decision-summary-grid');
  const laneGrid = screen.getByTestId('decision-lane-grid');
  const tradingLink = screen.getByRole('link', {
    name: 'Open Trading approvals: 贵州茅台 600519',
  });

  expect(summaryGrid.className).toContain('min-w-0');
  expect(laneGrid.className).toContain('min-w-0');
  expect(candidateCard.className).toContain('min-w-0');
  expect(candidateCard.className).toContain('break-words');
  expect(tradingLink.className).toContain('shrink-0');
  expect(tradingLink.className).toContain('whitespace-normal');

  for (const evidenceLine of screen.getAllByTestId('decision-evidence-line')) {
    expect(evidenceLine.className).toContain('min-w-0');
    expect(evidenceLine.textContent).toBeTruthy();
  }
});
