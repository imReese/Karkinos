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
      divergence_summary: {
        expected_strategy_behavior: {
          source_decision: 'buy',
          expected_order_count: 1,
          symbols: ['600519'],
          side_counts: { buy: 1 },
          strategy_refs: ['strategy_signal:dual_ma'],
          risk_refs: ['risk_decision:risk-001'],
          signal_refs: ['signal:signal-001'],
          risk_gate_status_counts: { passed: 1 },
          manual_confirmation_status_counts: {
            ready_for_manual_confirmation: 1,
          },
          submission_status_counts: { manual_pending: 1 },
        },
        execution_comparison: {
          matched_order_count: 1,
          missing_order_intent_refs: [],
          diverged_order_refs: ['paper_shadow_order:SHADOW-2026-06-12-9'],
          failed_order_refs: [],
          simulated_status_counts: { partially_filled: 1 },
          fill_count_by_order: { 'SHADOW-2026-06-12-9': 1 },
          filled_quantity_by_order: { 'SHADOW-2026-06-12-9': '40' },
          remaining_quantity_by_order: { 'SHADOW-2026-06-12-9': '60' },
        },
        realized_market_context: {
          symbol_count: 1,
          price_basis_counts: { latest_quote: 1 },
          symbols: [
            {
              symbol: '600519',
              expected_price: '10.00',
              price_basis: 'latest_quote',
              simulated_fill_prices: ['10.05'],
              simulated_slippage_cost: '2.00',
            },
          ],
        },
        cost_summary: {
          estimated_total_fee: '12.3',
          simulated_fee_tax_cost: '12.35',
          simulated_slippage_cost: '4.50',
          simulated_total_execution_cost: '16.85',
          fee_rule_ids: ['stock_a_commission_v1'],
          fill_count_with_cost_evidence: 1,
        },
        does_not_submit_broker_order: true,
        does_not_mutate_production_ledger: true,
      },
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
  automationCockpitResponse = {
    schema_version: 'karkinos.automation_cockpit.v1',
    broker_submission_enabled: false,
    automation_status: {
      schema_version: 'karkinos.automation_status.v1',
      default_execution_mode: 'paper_shadow',
      broker_submission_enabled: false,
      manual_confirmation_required: true,
      kill_switch_enabled: false,
      policies: {
        default: {
          policy_id: 'default',
          mode: 'paper_shadow',
          broker_submission_enabled: false,
          manual_confirmation_required: true,
          max_single_order_amount: 50000,
          max_daily_traded_amount: 100000,
          deny_buy_symbols: [],
          deny_sell_symbols: [],
        },
      },
      latest_runs: [],
      limitations: ['Live broker submission is disabled by default.'],
    },
    gateways: [
      {
        gateway_id: 'manual_ticket',
        status: 'available',
        mode: 'manual_confirmation',
        capabilities: ['create_manual_ticket'],
        limitations: ['Creates a manual ticket only.'],
      },
      {
        gateway_id: 'live_disabled',
        status: 'disabled',
        mode: 'live',
        capabilities: [],
        limitations: ['Live submission is disabled.'],
      },
    ],
    open_alert_count: 1,
    open_alerts: [
      {
        id: 7,
        alert_type: 'execution_reconciliation_gap',
        severity: 'warning',
        status: 'open',
        title: 'Execution reconciliation needs review',
        detail: '2 OMS items need broker evidence.',
        created_at: '2026-06-12T09:33:00+08:00',
      },
    ],
    recent_runs: [
      {
        run_id: 'market-session:2026-06-12:0931',
        run_type: 'market_session',
        mode: 'paper_shadow',
        status: 'blocked',
        started_at: '2026-06-12T09:31:00+08:00',
        finished_at: '2026-06-12T09:31:01+08:00',
        reason: 'outside_market_session',
      },
    ],
    promotion_states: [
      {
        strategy_id: 'dual_ma',
        stage: 'paper_shadow',
        status: 'active',
        updated_at: '2026-06-12T09:30:00+08:00',
      },
    ],
    execution_reconciliation_open_items: [
      {
        item_id: 1,
        order_id: 'OMS-1',
        status: 'awaiting_manual_confirmation',
        recommended_action: 'review_manual_confirmation',
      },
      {
        item_id: 2,
        order_id: 'OMS-2',
        status: 'awaiting_broker_evidence',
        recommended_action: 'import_broker_evidence',
      },
    ],
    limitations: [
      'Cockpit summary is read-only and does not submit broker orders.',
    ],
  },
  brokerGatewayStatusResponse = {
    schema_version: 'karkinos.broker_gateway_status.v1',
    broker_submission_enabled: false,
    kill_switch_enabled: false,
    kill_switch_reason: '',
    gateways: [
      {
        gateway_id: 'manual_ticket',
        display_name: 'Manual ticket',
        status: 'available',
        can_preview_orders: true,
        can_export_tickets: true,
        can_dry_run_orders: true,
        can_submit_orders: false,
        can_cancel_orders: false,
        can_query_orders: true,
        can_query_fills: true,
        can_query_positions: false,
        can_query_cash: false,
        blockers: [],
        limitations: ['Manual ticket only; no broker order is submitted.'],
      },
      {
        gateway_id: 'live_disabled',
        display_name: 'Live broker execution',
        status: 'disabled',
        can_preview_orders: false,
        can_export_tickets: false,
        can_dry_run_orders: false,
        can_submit_orders: false,
        can_cancel_orders: false,
        can_query_orders: false,
        can_query_fills: false,
        can_query_positions: false,
        can_query_cash: false,
        blockers: ['live_broker_disabled'],
        blocked_reason: 'Live broker submission is disabled by default.',
        limitations: ['Live broker submission remains disabled.'],
      },
    ],
  },
  brokerConnectorHealthResponse = {
    schema_version: 'karkinos.broker_connector_health_list.v1',
    broker_submission_enabled: false,
    connectors: [],
  },
  brokerAccountFactsResponse = {
    schema_version: 'karkinos.broker_gateway_status.v1',
    gateway_id: 'staged_broker_evidence',
    status: 'empty',
    query_scope: 'staged_broker_evidence',
    submitted_to_broker: false,
    can_submit_orders: false,
    source_import_run_ids: [],
    broker_event_count: 0,
    cash_balances: [],
    positions: [],
    fills: [],
    limitations: ['This query reads staged broker evidence only.'],
  },
  brokerFillsQueryResponse = {
    schema_version: 'karkinos.broker_gateway.v1',
    gateway_id: 'staged_broker_evidence',
    status: 'empty',
    query_scope: 'staged_broker_fills',
    submitted_to_broker: false,
    can_submit_orders: false,
    symbol: null,
    source_import_run_ids: [],
    broker_event_count: 0,
    fill_count: 0,
    fills: [],
    limitations: ['This query reads staged broker fill evidence only.'],
  },
  brokerOrderQueryResponse = {
    schema_version: 'karkinos.broker_gateway.v1',
    gateway_id: 'manual_ticket',
    status: 'empty',
    query_scope: 'local_audit_and_staged_broker_evidence',
    submitted_to_broker: false,
    can_submit_orders: false,
    oms_order: null,
    gateway_event_count: 0,
    gateway_events: [],
    staged_broker_fill_count: 0,
    staged_broker_fills: [],
    limitations: ['This query reads local Karkinos facts only.'],
  },
  executionReconciliationRunsResponse = [],
  executionReconciliationRunDetailResponse = undefined,
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
  automationCockpitResponse?: unknown;
  brokerGatewayStatusResponse?: unknown;
  brokerConnectorHealthResponse?: unknown;
  brokerAccountFactsResponse?: unknown;
  brokerFillsQueryResponse?: unknown;
  brokerOrderQueryResponse?: unknown;
  executionReconciliationRunsResponse?: unknown;
  executionReconciliationRunDetailResponse?: unknown;
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
      if (url.includes('/api/automation/cockpit')) {
        return jsonResponse(automationCockpitResponse);
      }
      if (url.includes('/api/broker-gateway/status')) {
        return jsonResponse(brokerGatewayStatusResponse);
      }
      if (url.includes('/api/broker-gateway/connectors/health')) {
        return jsonResponse(brokerConnectorHealthResponse);
      }
      if (url.includes('/api/broker-gateway/account-facts')) {
        return jsonResponse(brokerAccountFactsResponse);
      }
      if (url.includes('/api/broker-gateway/fills/query')) {
        return jsonResponse(brokerFillsQueryResponse);
      }
      if (url.includes('/api/broker-gateway/orders/')) {
        return jsonResponse(brokerOrderQueryResponse);
      }
      if (url.includes('/api/execution-reconciliation/runs/')) {
        const executionReconciliationRunDetail =
          executionReconciliationRunDetailResponse ??
          (Array.isArray(executionReconciliationRunsResponse)
            ? executionReconciliationRunsResponse[0]
            : executionReconciliationRunsResponse);
        return jsonResponse(executionReconciliationRunDetail ?? null);
      }
      if (url.includes('/api/execution-reconciliation/runs')) {
        return jsonResponse(executionReconciliationRunsResponse);
      }
      if (url.includes('/api/operations/paper-shadow/run')) {
        return jsonResponse({
          run_id: 'shadow:2026-06-12:abc123',
          status: 'within_expectations',
          does_not_submit_broker_order: true,
          does_not_mutate_production_ledger: true,
        });
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
  expect(plan.textContent).toContain('Sim fee/tax');
  expect(plan.textContent).toContain('¥12.35');
  expect(plan.textContent).toContain('Sim slippage');
  expect(plan.textContent).toContain('¥4.50');
  expect(plan.textContent).toContain('Sim total cost');
  expect(plan.textContent).toContain('¥16.85');
  expect(plan.textContent).toContain('stock_a_commission_v1');
  expect(plan.textContent).toContain('Expected strategy behavior');
  expect(plan.textContent).toContain('Expected orders: 1');
  expect(plan.textContent).toContain('Decision: Buy');
  expect(plan.textContent).toContain('Symbols: 600519');
  expect(plan.textContent).toContain('Sides: Buy: 1');
  expect(plan.textContent).toContain('Strategy signal · dual_ma');
  expect(plan.textContent).toContain('Execution comparison');
  expect(plan.textContent).toContain('Matched orders: 1');
  expect(plan.textContent).toContain(
    'Diverged orders: Simulation review order · SHADOW-2026-06-12-9',
  );
  expect(plan.textContent).toContain('Sim statuses: partially filled: 1');
  expect(plan.textContent).toContain('Filled qty: SHADOW-2026-06-12-9: 40');
  expect(plan.textContent).toContain('Remaining qty: SHADOW-2026-06-12-9: 60');
  expect(plan.textContent).toContain('Realized market context');
  expect(plan.textContent).toContain('Price basis: latest quote: 1');
  expect(plan.textContent).toContain(
    '600519 · expected ¥10.00 · fills ¥10.05 · slippage ¥2.00',
  );
  expect(plan.textContent).toContain(
    'Simulation evidence only; no broker submission',
  );
  expect(plan.textContent).toContain('Does not mutate production ledger');
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

test('runs paper shadow simulation from the daily trading plan panel', async () => {
  const { fetchMock } = renderDecisionCockpit();

  const plan = await screen.findByTestId('decision-daily-trading-plan');
  fireEvent.click(
    within(plan).getByRole('button', { name: 'Run paper/shadow simulation' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/operations/paper-shadow/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

test('renders failed paper shadow runs with a public recovery action', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
      schema_version: 'karkinos.operations_today.v1',
      operations_date: '2026-06-12',
      generated_at: '2026-06-12T09:32:00+08:00',
      conclusion_status: 'blocked',
      primary_target: 'paper-shadow',
      health: {
        total: 8,
        pass: 5,
        degraded: 0,
        blocked: 1,
        manual_action_required: 1,
        skipped: 1,
      },
      subsystems: [],
      daily_plan: {
        candidate_pool_count: 1,
        manual_ready_count: 1,
        blocked_count: 0,
        order_intent_count: 1,
        conclusion_status: 'manual_confirmation_ready',
      },
      paper_shadow: {
        status: 'failed',
        run_id: 'shadow:2026-06-12:failed',
        input_fingerprint: 'failed',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 1,
        divergence_status: 'failed',
        next_manual_review_step: 'inspect_failed_run',
        last_run_at: '2026-06-12T09:32:00+08:00',
        limitations: ['Paper/shadow simulation failed: fixture error'],
        orders: [
          {
            order_id: 'SHADOW-FAILED',
            symbol: '600519',
            status: 'failed',
            divergence_status: 'failed',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Failed');
  expect(plan.textContent).toContain(
    'Inspect failed paper/shadow run before approval',
  );
  expect(plan.textContent).not.toContain('inspect_failed_run');
});

test('renders paper shadow review queue as public operator review items', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
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
          last_run_at: '2026-06-12T09:32:00+08:00',
          next_action: 'resolve_shadow_divergence',
          limitations: [],
          detail_status: 'diverged',
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
        status: 'diverged',
        run_id: 'shadow:2026-06-12:partial',
        input_fingerprint: 'partial',
        input_snapshot: {
          schema_version: 'karkinos.paper_shadow_run.input_snapshot.v1',
          plan_date: '2026-06-12',
          input_fingerprint: 'partial',
          source_decision: 'buy',
          order_intent_count: 1,
          does_not_submit_broker_order: true,
          does_not_mutate_production_ledger: true,
        },
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 1,
        divergence_reviewed_count: 0,
        divergence_status: 'diverged',
        next_manual_review_step: 'resolve_shadow_divergence',
        last_run_at: '2026-06-12T09:32:00+08:00',
        review_queue: [
          {
            review_id: 'shadow:2026-06-12:partial:ACTION-1',
            order_intent_ref: 'action:ACTION-1',
            order_id: 'SHADOW-PARTIAL',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
            severity: 'warning',
            required_action: 'resolve_shadow_divergence',
            reason:
              'Paper/shadow order partially_filled; compare simulated execution with the original order intent before manual confirmation.',
            strategy_refs: ['strategy:dual_ma'],
            risk_refs: ['risk:risk-001'],
            signal_refs: ['signal:signal-001'],
            evidence_refs: [
              'action:ACTION-1',
              'strategy:dual_ma',
              'risk:risk-001',
              'signal:signal-001',
              'paper_order:SHADOW-PARTIAL',
              'paper_fill:SHADOW-PARTIAL-FILL-1',
            ],
            account_truth: {
              gate_status: 'pass',
              has_evidence: true,
              blocking_reasons: [],
            },
            risk_gate_status: 'passed',
            manual_confirmation_status: 'ready_for_manual_confirmation',
            submission_status: 'manual_confirmation_required',
            cash_status: 'sufficient',
            constraint_status_counts: { pass: 2 },
            cost_evidence: {
              estimated_gross_amount: '74070',
              estimated_total_fee: '12.30',
              simulated_fee_tax_cost: '12.45',
              simulated_slippage_cost: '30.00',
              fee_rule_id: 'stock_a_commission_v1',
            },
            market_context: {
              price_basis: 'estimated_price',
              expected_price: '123.45',
              simulated_fill_prices: ['123.50'],
            },
            oms_status_path: [
              'staged',
              'submitted',
              'accepted',
              'partially_filled',
            ],
            oms_transition_refs: [
              'oms_transition:SHADOW-PARTIAL:1:staged',
              'oms_transition:SHADOW-PARTIAL:2:submitted',
              'oms_transition:SHADOW-PARTIAL:3:accepted',
              'oms_transition:SHADOW-PARTIAL:4:partially_filled',
            ],
            oms_transitions: [
              {
                sequence: 1,
                from_status: null,
                to_status: 'staged',
                source: 'paper_shadow_daily',
                reason: '',
                filled_quantity: '0',
                does_not_submit_broker_order: true,
                does_not_mutate_production_ledger: true,
              },
              {
                sequence: 2,
                from_status: 'staged',
                to_status: 'submitted',
                source: 'paper_shadow_daily',
                reason: '',
                filled_quantity: '0',
                does_not_submit_broker_order: true,
                does_not_mutate_production_ledger: true,
              },
              {
                sequence: 3,
                from_status: 'submitted',
                to_status: 'accepted',
                source: 'paper_shadow_daily',
                reason: '',
                filled_quantity: '0',
                does_not_submit_broker_order: true,
                does_not_mutate_production_ledger: true,
              },
              {
                sequence: 4,
                from_status: 'accepted',
                to_status: 'partially_filled',
                source: 'paper_shadow_daily',
                reason: '',
                filled_quantity: '40',
                does_not_submit_broker_order: true,
                does_not_mutate_production_ledger: true,
              },
            ],
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
        ],
        orders: [
          {
            order_id: 'SHADOW-PARTIAL',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Review queue');
  expect(plan.textContent).toContain(
    '600519 · Resolve simulation divergence before approval',
  );
  expect(plan.textContent).toContain('Risk Passed · Manual Ready');
  expect(plan.textContent).toContain('Account truth Pass · Cash Sufficient');
  expect(plan.textContent).toContain('Constraints Pass: 2');
  expect(plan.textContent).toContain('Projected fee ¥12.30');
  expect(plan.textContent).toContain('Sim fee/tax ¥12.45');
  expect(plan.textContent).toContain('Sim slippage ¥30.00');
  expect(plan.textContent).toContain('Expected ¥123.45 · Fill ¥123.50');
  expect(plan.textContent).toContain(
    'OMS path: Staged > Submitted > Accepted > Partially Filled',
  );
  expect(plan.textContent).toContain(
    'OMS transition: SHADOW-PARTIAL #4 Partially Filled',
  );
  expect(plan.textContent).toContain('Strategy · dual_ma');
  expect(plan.textContent).toContain('Risk check · risk-001');
  expect(plan.textContent).toContain('Signal evidence · signal-001');
  expect(plan.textContent).toContain(
    'Simulation review order · SHADOW-PARTIAL',
  );
  expect(plan.textContent).toContain(
    'Simulation review fill · SHADOW-PARTIAL-FILL-1',
  );
  expect(plan.textContent).toContain('No broker submission');
  expect(plan.textContent).toContain('No production ledger mutation');
  expect(plan.textContent).toContain(
    'Input snapshot: 1 order intent · Source Buy · Fingerprint partial',
  );
  expect(plan.textContent).toContain(
    'Snapshot safety: No broker submission · No production ledger mutation',
  );
  expect(plan.textContent).not.toContain('resolve_shadow_divergence');
  expect(plan.textContent).not.toContain('partially_filled');
  expect(plan.textContent).not.toContain('oms_transition:');
  expect(plan.textContent).not.toContain(
    'karkinos.paper_shadow_run.input_snapshot.v1',
  );
  expect(plan.textContent).not.toContain('Submit broker order');
});

test('renders terminal paper shadow review reasons without raw reason codes', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
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
          last_run_at: '2026-06-12T09:32:00+08:00',
          next_action: 'resolve_shadow_divergence',
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
        run_id: 'shadow:2026-06-12:cancelled',
        input_fingerprint: 'cancelled',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 0,
        divergence_status: 'review_required',
        next_manual_review_step: 'resolve_shadow_divergence',
        last_run_at: '2026-06-12T09:32:00+08:00',
        review_queue: [
          {
            review_id: 'shadow:2026-06-12:cancelled:ACTION-1',
            order_intent_ref: 'action:ACTION-1',
            order_id: 'SHADOW-CANCELLED',
            symbol: '600519',
            status: 'cancelled',
            divergence_status: 'review_required',
            severity: 'warning',
            required_action: 'resolve_shadow_divergence',
            reason:
              'Paper/shadow order cancelled; review terminal simulation reason before manual confirmation.',
            terminal_status: 'cancelled',
            terminal_reason: 'operator_cancelled',
            terminal_oms_transition_ref:
              'oms_transition:SHADOW-CANCELLED:4:cancelled',
            oms_status_path: ['staged', 'submitted', 'accepted', 'cancelled'],
            oms_transition_refs: [
              'oms_transition:SHADOW-CANCELLED:1:staged',
              'oms_transition:SHADOW-CANCELLED:2:submitted',
              'oms_transition:SHADOW-CANCELLED:3:accepted',
              'oms_transition:SHADOW-CANCELLED:4:cancelled',
            ],
            oms_transitions: [
              {
                sequence: 4,
                from_status: 'accepted',
                to_status: 'cancelled',
                source: 'paper_shadow_daily',
                reason: 'operator_cancelled',
                filled_quantity: '0',
                does_not_submit_broker_order: true,
                does_not_mutate_production_ledger: true,
              },
            ],
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
        ],
        orders: [
          {
            order_id: 'SHADOW-CANCELLED',
            symbol: '600519',
            status: 'cancelled',
            divergence_status: 'review_required',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain(
    'Terminal outcome: Cancelled · Operator cancelled simulation before fill · OMS transition · SHADOW-CANCELLED #4 Cancelled',
  );
  expect(plan.textContent).not.toContain('operator_cancelled');
  expect(plan.textContent).not.toContain('terminal_reason');
  expect(plan.textContent).not.toContain('Submit broker order');
});

test('renders paper shadow manual handoff gate as public operator evidence', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
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
          last_run_at: '2026-06-12T09:32:00+08:00',
          next_action: 'resolve_shadow_divergence',
          limitations: [],
          detail_status: 'diverged',
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
        status: 'diverged',
        run_id: 'shadow:2026-06-12:partial',
        input_fingerprint: 'partial',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 1,
        divergence_reviewed_count: 0,
        divergence_status: 'diverged',
        next_manual_review_step: 'resolve_shadow_divergence',
        last_run_at: '2026-06-12T09:32:00+08:00',
        manual_handoff: {
          ready: false,
          status: 'blocked_by_unresolved_divergence',
          blockers: ['unresolved_paper_shadow_divergence'],
          required_actions: ['resolve_shadow_divergence'],
          review_queue_count: 1,
          highest_severity: 'warning',
          review_status: null,
          reviewed_at: null,
          reviewer: null,
          does_not_submit_broker_order: true,
          does_not_mutate_production_ledger: true,
        },
        review_queue: [],
        orders: [
          {
            order_id: 'SHADOW-PARTIAL',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain(
    'Manual handoff: Blocked by unresolved simulation divergence',
  );
  expect(plan.textContent).toContain(
    'Next: Resolve simulation divergence before approval',
  );
  expect(plan.textContent).toContain('Review queue: 1 item');
  expect(plan.textContent).toContain('No broker submission');
  expect(plan.textContent).toContain('No production ledger mutation');
  expect(plan.textContent).not.toContain('blocked_by_unresolved_divergence');
  expect(plan.textContent).not.toContain('unresolved_paper_shadow_divergence');
  expect(plan.textContent).not.toContain('resolve_shadow_divergence');
  expect(plan.textContent).not.toContain('Submit broker order');
});

test('renders running paper shadow runs as a wait state', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
      schema_version: 'karkinos.operations_today.v1',
      operations_date: '2026-06-12',
      generated_at: '2026-06-12T09:32:00+08:00',
      conclusion_status: 'degraded',
      primary_target: 'paper-shadow',
      health: {
        total: 8,
        pass: 5,
        degraded: 1,
        blocked: 0,
        manual_action_required: 1,
        skipped: 1,
      },
      subsystems: [
        {
          id: 'paper_shadow',
          status: 'degraded',
          tone: 'warning',
          target: 'paper-shadow',
          last_run_at: '2026-06-12T09:32:00+08:00',
          next_action: 'wait_for_paper_shadow_run',
          limitations: [],
          detail_status: 'running',
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
        status: 'running',
        run_id: 'shadow:2026-06-12:running',
        input_fingerprint: 'running',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 0,
        divergence_status: 'running',
        next_manual_review_step: 'wait_for_paper_shadow_run',
        last_run_at: '2026-06-12T09:32:00+08:00',
        orders: [
          {
            order_id: 'SHADOW-RUNNING',
            symbol: '600519',
            status: 'submitted',
            divergence_status: 'running',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Running');
  expect(plan.textContent).toContain(
    'Paper/shadow simulation is running; wait for completion',
  );
  expect(plan.textContent).not.toContain('wait_for_paper_shadow_run');
  expect(plan.textContent).not.toContain(
    'Review paper/shadow divergence evidence',
  );
});

test('renders accepted paper shadow divergence review as manual confirmation handoff', async () => {
  renderDecisionCockpit({
    operationsTodayResponse: {
      schema_version: 'karkinos.operations_today.v1',
      operations_date: '2026-06-12',
      generated_at: '2026-06-12T09:32:00+08:00',
      conclusion_status: 'manual_action_required',
      primary_target: 'trading',
      health: {
        total: 8,
        pass: 6,
        degraded: 0,
        blocked: 0,
        manual_action_required: 1,
        skipped: 1,
      },
      subsystems: [
        {
          id: 'paper_shadow',
          status: 'pass',
          tone: 'success',
          target: 'paper-shadow',
          last_run_at: '2026-06-12T10:10:00+08:00',
          next_action: 'review_manual_confirmation',
          limitations: [],
          detail_status: 'accepted_for_manual_confirmation',
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
        status: 'diverged',
        effective_status: 'accepted_for_manual_confirmation',
        run_id: 'shadow:2026-06-12:accepted',
        input_fingerprint: 'accepted',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 1,
        divergence_status: 'diverged',
        review_status: 'accepted_for_manual_confirmation',
        reviewed_at: '2026-06-12T10:10:00+08:00',
        reviewer: 'local-operator',
        next_manual_review_step: 'review_manual_confirmation',
        orders: [
          {
            order_id: 'SHADOW-ACCEPTED',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
          },
        ],
      },
      limitations: [],
    },
  });

  const plan = await screen.findByTestId('decision-daily-trading-plan');

  expect(plan.textContent).toContain('Accepted for manual confirmation');
  expect(plan.textContent).toContain(
    'Simulation reviewed; continue with manual confirmation',
  );
  expect(plan.textContent).not.toContain('resolve_shadow_divergence');
  expect(plan.textContent).not.toContain('Submit broker order');
});

test('summarizes controlled automation cockpit status in the decision page', async () => {
  renderDecisionCockpit();

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Automation to-do');
  expect(automation.textContent).toContain(
    'Manual confirmation remains default',
  );
  expect(automation.textContent).toContain('Broker submission off');
  expect(automation.textContent).toContain('1 open alert');
  expect(automation.textContent).toContain('2 reconciliation reviews');
  expect(automation.textContent).toContain('Next: import broker evidence');
  expect(automation.textContent).toContain('paper/shadow only');
  expect(automation.textContent).not.toContain('execution_reconciliation_gap');
});

test('surfaces broker gateway status without execution controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    brokerGatewayStatusResponse: {
      schema_version: 'karkinos.broker_gateway_status.v1',
      broker_submission_enabled: false,
      kill_switch_enabled: true,
      kill_switch_reason: 'Operator pause for reconciliation review.',
      gateways: [
        {
          gateway_id: 'manual_ticket',
          display_name: 'Manual ticket',
          status: 'blocked_by_kill_switch',
          can_preview_orders: false,
          can_export_tickets: false,
          can_dry_run_orders: false,
          can_submit_orders: false,
          can_cancel_orders: false,
          blockers: ['kill_switch'],
          blocked_reason: 'Kill switch is active.',
          limitations: ['Manual ticket creation is blocked by kill switch.'],
        },
        {
          gateway_id: 'live_disabled',
          display_name: 'Live broker execution',
          status: 'disabled',
          can_preview_orders: false,
          can_export_tickets: false,
          can_dry_run_orders: false,
          can_submit_orders: false,
          can_cancel_orders: false,
          blockers: ['live_broker_disabled'],
          blocked_reason: 'Live broker submission is disabled by default.',
          limitations: ['Live broker submission remains disabled.'],
        },
      ],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Broker gateway status');
  expect(automation.textContent).toContain('Kill switch active');
  expect(automation.textContent).toContain(
    'Operator pause for reconciliation review.',
  );
  expect(automation.textContent).toContain('Manual ticket');
  expect(automation.textContent).toContain('Blocked by kill switch');
  expect(automation.textContent).toContain('Preview blocked');
  expect(automation.textContent).toContain('Export blocked');
  expect(automation.textContent).toContain('Dry run blocked');
  expect(automation.textContent).toContain('Live broker execution');
  expect(automation.textContent).toContain('Disabled');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces manual ticket export capability as read-only gateway status', async () => {
  renderDecisionCockpit({
    locale: 'en',
    brokerGatewayStatusResponse: {
      schema_version: 'karkinos.broker_gateway_status.v1',
      broker_submission_enabled: false,
      kill_switch_enabled: false,
      gateways: [
        {
          gateway_id: 'manual_ticket',
          display_name: 'Manual ticket',
          status: 'available',
          can_preview_orders: true,
          can_export_tickets: true,
          can_dry_run_orders: true,
          can_submit_orders: false,
          can_cancel_orders: false,
          can_query_orders: true,
          can_query_fills: true,
          can_query_positions: false,
          can_query_cash: false,
          blockers: [],
          limitations: ['Creates manual tickets only.'],
        },
        {
          gateway_id: 'live_disabled',
          display_name: 'Live broker execution',
          status: 'disabled',
          can_preview_orders: false,
          can_export_tickets: false,
          can_dry_run_orders: false,
          can_submit_orders: false,
          can_cancel_orders: false,
          can_query_orders: false,
          can_query_fills: false,
          can_query_positions: false,
          can_query_cash: false,
          blockers: ['live_broker_disabled'],
          limitations: ['Live broker submission remains disabled.'],
        },
      ],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Manual ticket');
  expect(automation.textContent).toContain('Export available');
  expect(automation.textContent).toContain('Query orders available');
  expect(automation.textContent).toContain('Query fills available');
  expect(automation.textContent).toContain('Read positions blocked');
  expect(automation.textContent).toContain('Read cash blocked');
  expect(automation.textContent).toContain('Submit blocked');
  expect(automation.textContent).toContain('Live broker execution');
  expect(automation.textContent).toContain('Export blocked');
  expect(automation.textContent).toContain('Query orders blocked');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces controlled bridge policy whitelist as non-submitting evidence', async () => {
  renderDecisionCockpit({
    locale: 'en',
    brokerGatewayStatusResponse: {
      schema_version: 'karkinos.broker_gateway_status.v1',
      broker_submission_enabled: false,
      kill_switch_enabled: false,
      controlled_bridge_policy: {
        schema_version: 'karkinos.controlled_broker_bridge_policy.v1',
        policy_id: 'local-controlled-bridge-review',
        status: 'configured_non_submitting',
        enabled: true,
        broker_submission_enabled: false,
        live_submission_available: false,
        automation_allowed: false,
        per_order_confirmation_required: true,
        allowed_connector_ids: ['local-qmt-readonly'],
        allowed_account_aliases: ['local-review'],
        allowed_strategy_ids: ['dual_ma'],
        allowed_symbols: ['600519'],
        required_gates: [
          'account_truth',
          'research_evidence',
          'risk',
          'paper_shadow',
          'manual_confirmation',
          'kill_switch_clear',
          'connector_health',
          'execution_reconciliation',
        ],
        blockers: ['live_gateway_not_implemented'],
      },
      gateways: [
        {
          gateway_id: 'manual_ticket',
          display_name: 'Manual ticket',
          status: 'available',
          can_preview_orders: true,
          can_export_tickets: true,
          can_dry_run_orders: true,
          can_submit_orders: false,
          can_cancel_orders: false,
          blockers: [],
          limitations: ['Creates manual tickets only.'],
        },
        {
          gateway_id: 'live_disabled',
          display_name: 'Live broker execution',
          status: 'disabled',
          can_preview_orders: false,
          can_export_tickets: false,
          can_dry_run_orders: false,
          can_submit_orders: false,
          can_cancel_orders: false,
          can_query_orders: false,
          can_query_fills: false,
          can_query_positions: false,
          can_query_cash: false,
          controlled_bridge_policy_status: 'configured_non_submitting',
          blockers: ['live_broker_disabled'],
          limitations: ['Live broker submission remains disabled.'],
        },
      ],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Controlled bridge policy');
  expect(automation.textContent).toContain('Configured, no submission');
  expect(automation.textContent).toContain('local-controlled-bridge-review');
  expect(automation.textContent).toContain('Connector: local-qmt-readonly');
  expect(automation.textContent).toContain('Account: local-review');
  expect(automation.textContent).toContain('Strategy: dual_ma');
  expect(automation.textContent).toContain('Symbol: 600519');
  expect(automation.textContent).toContain('Required gates');
  expect(automation.textContent).toContain('account truth');
  expect(automation.textContent).toContain('execution reconciliation');
  expect(automation.textContent).toContain('live gateway not implemented');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces read-only connector health and staged account facts without credentials or live actions', async () => {
  renderDecisionCockpit({
    locale: 'en',
    brokerConnectorHealthResponse: {
      schema_version: 'karkinos.broker_connector_health_list.v1',
      broker_submission_enabled: false,
      connectors: [
        {
          schema_version: 'karkinos.broker_connector_health.v1',
          connector_id: 'local-qmt-readonly',
          connector_type: 'qmt_readonly',
          enabled: true,
          status: 'configured_readonly_unverified',
          message:
            'Read-only connector is configured; live client health is not checked.',
          account_alias: 'local-review',
          capability_scope: 'local_readonly_connector_contract',
          capabilities: {
            can_read_health: true,
            can_read_account: true,
            can_read_cash: true,
            can_read_positions: true,
            can_read_orders: true,
            can_read_fills: true,
            can_preview_orders: false,
            can_export_tickets: false,
            can_dry_run_orders: false,
            can_submit_orders: false,
            can_cancel_orders: false,
          },
          requires_credentials: false,
          stores_credentials: false,
          submitted_to_broker: false,
          limitations: [
            'Connector health is a local configuration contract only.',
          ],
        },
      ],
    },
    brokerAccountFactsResponse: {
      schema_version: 'karkinos.broker_gateway_status.v1',
      gateway_id: 'staged_broker_evidence',
      status: 'available',
      query_scope: 'staged_broker_evidence',
      submitted_to_broker: false,
      can_submit_orders: false,
      source_import_run_ids: ['import-run-1'],
      broker_event_count: 3,
      cash_balances: [{ currency: 'CNY', cash_balance: '100000.00' }],
      positions: [{ symbol: '600519', quantity: '100' }],
      fills: [{ event_id: 'broker-buy-600519', symbol: '600519' }],
      limitations: ['This query reads staged broker evidence only.'],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Read-only connector health');
  expect(automation.textContent).toContain('local-qmt-readonly');
  expect(automation.textContent).toContain('Configured readonly unverified');
  expect(automation.textContent).toContain('Read account available');
  expect(automation.textContent).toContain('Read cash available');
  expect(automation.textContent).toContain('Read positions available');
  expect(automation.textContent).toContain('Read orders available');
  expect(automation.textContent).toContain('Read fills available');
  expect(automation.textContent).toContain('Preview orders blocked');
  expect(automation.textContent).toContain('Export tickets blocked');
  expect(automation.textContent).toContain('Dry-run orders blocked');
  expect(automation.textContent).toContain('Submit blocked');
  expect(automation.textContent).toContain('Cancel blocked');
  expect(automation.textContent).toContain('Staged account facts');
  expect(automation.textContent).toContain('3 broker evidence events');
  expect(automation.textContent).toContain('1 cash');
  expect(automation.textContent).toContain('1 position');
  expect(automation.textContent).toContain('1 fill');
  expect(automation.textContent).not.toContain('client_path');
  expect(automation.textContent).not.toContain('/Applications/QMT');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces runtime connector snapshot evidence without account ids or live actions', async () => {
  renderDecisionCockpit({
    locale: 'en',
    automationCockpitResponse: {
      schema_version: 'karkinos.automation_cockpit.v1',
      broker_submission_enabled: false,
      automation_status: {
        schema_version: 'karkinos.automation_status.v1',
        mode: 'paper_shadow',
        broker_submission_enabled: false,
        manual_confirmation_required: true,
        kill_switch_enabled: false,
      },
      gateways: [],
      open_alert_count: 0,
      open_alerts: [],
      recent_runs: [],
      promotion_states: [],
      execution_reconciliation_open_items: [],
      runtime_connector_snapshots: [
        {
          schema_version: 'karkinos.broker_gateway.v1',
          gateway_id: 'read_only_connector',
          status: 'snapshot_ready',
          query_scope: 'runtime_readonly_connector_snapshot',
          connector_id: 'fake-qmt-runtime',
          account_alias: 'local-review',
          captured_at: '2026-07-02T09:31:00+08:00',
          connector_health: {
            status: 'runtime_healthy',
            raw_status: 'healthy',
            message: 'Read-only connector heartbeat is healthy.',
            checked_at: '2026-07-02T09:30:00+08:00',
          },
          cash_balance: {
            currency: 'CNY',
            balance: '100000.00',
            available: '88000.00',
          },
          position_count: 1,
          positions: [{ symbol: '600519', quantity: '200' }],
          order_count: 1,
          orders: [{ order_id: 'broker-order-private', symbol: '600519' }],
          fill_count: 1,
          fills: [{ fill_id: 'fill-001', symbol: '600519' }],
          capabilities: {
            can_read_account: true,
            can_read_cash: true,
            can_read_positions: true,
            can_read_orders: true,
            can_read_fills: true,
            can_submit_orders: false,
            can_cancel_orders: false,
          },
          submitted_to_broker: false,
          does_not_mutate_oms: true,
          does_not_mutate_production_ledger: true,
          limitations: [
            'Read-only connector snapshot query is runtime evidence only.',
          ],
        },
      ],
      limitations: [],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Runtime connector snapshot');
  expect(automation.textContent).toContain('fake-qmt-runtime');
  expect(automation.textContent).toContain('Snapshot ready');
  expect(automation.textContent).toContain('Cash CNY 100000.00');
  expect(automation.textContent).toContain('1 position');
  expect(automation.textContent).toContain('1 order');
  expect(automation.textContent).toContain('1 fill');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).not.toContain('private-account-id');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
  expect(automation.textContent).not.toContain('Sync ledger');
});

test('surfaces strategy promotion state as paper shadow only without live promotion controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    automationCockpitResponse: {
      schema_version: 'karkinos.automation_cockpit.v1',
      broker_submission_enabled: false,
      automation_status: {
        schema_version: 'karkinos.automation_status.v1',
        mode: 'paper_shadow',
        default_execution_mode: 'paper_shadow',
        broker_submission_enabled: false,
        manual_confirmation_required: true,
        kill_switch_enabled: false,
        next_action: 'paper_shadow_available',
        limitations: ['Live submission remains disabled.'],
      },
      gateways: [],
      open_alert_count: 0,
      open_alerts: [],
      recent_runs: [],
      promotion_states: [
        {
          strategy_id: 'dual_ma',
          stage: 'paper_shadow',
          gate_status: 'paper_shadow_enabled',
          live_like_enabled: false,
          missing_requirements: [],
          backtest_result_id: 7,
          status: 'active',
          updated_at: '2026-06-12T09:30:00+08:00',
        },
      ],
      execution_reconciliation_open_items: [],
      limitations: [
        'Cockpit summary is read-only and does not submit broker orders.',
      ],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Strategy promotion state');
  expect(automation.textContent).toContain('dual_ma');
  expect(automation.textContent).toContain('Paper/shadow');
  expect(automation.textContent).toContain('Paper/shadow enabled');
  expect(automation.textContent).toContain('Live-like disabled');
  expect(automation.textContent).toContain('No missing requirements');
  expect(automation.textContent).not.toContain('Promote live');
  expect(automation.textContent).not.toContain('Enable live trading');
  expect(automation.textContent).not.toContain('Submit broker order');
});

test('surfaces strategy promotion lifecycle audit boundary without bridge controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    automationCockpitResponse: {
      schema_version: 'karkinos.automation_cockpit.v1',
      broker_submission_enabled: false,
      automation_status: {
        schema_version: 'karkinos.automation_status.v1',
        mode: 'paper_shadow',
        default_execution_mode: 'paper_shadow',
        broker_submission_enabled: false,
        manual_confirmation_required: true,
        kill_switch_enabled: false,
        next_action: 'paper_shadow_available',
        limitations: ['Live submission remains disabled.'],
      },
      gateways: [],
      open_alert_count: 0,
      open_alerts: [],
      recent_runs: [],
      promotion_states: [
        {
          strategy_id: 'dual_ma',
          stage: 'paused',
          gate_status: 'paused',
          live_like_enabled: false,
          missing_requirements: [],
          backtest_result_id: 7,
          updated_at: '2026-07-07T10:30:00+08:00',
          lifecycle: {
            audit_only: true,
            does_not_authorize_execution: true,
            disabled_stages: ['controlled_bridge_pilot', 'live_like'],
            allowed_operator_actions: ['review_readiness', 'retire'],
            terminal: false,
          },
        },
      ],
      execution_reconciliation_open_items: [],
      limitations: [
        'Cockpit summary is read-only and does not submit broker orders.',
      ],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Strategy promotion state');
  expect(automation.textContent).toContain('Paused');
  expect(automation.textContent).toContain('Lifecycle audit only');
  expect(automation.textContent).toContain('Does not authorize execution');
  expect(automation.textContent).toContain('Controlled bridge pilot disabled');
  expect(automation.textContent).toContain('Live-like disabled');
  expect(automation.textContent).not.toContain('Enable bridge pilot');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces staged fill polling evidence without live broker actions', async () => {
  const fetchMock = renderDecisionCockpit({
    locale: 'en',
    brokerFillsQueryResponse: {
      schema_version: 'karkinos.broker_gateway.v1',
      gateway_id: 'staged_broker_evidence',
      status: 'available',
      query_scope: 'staged_broker_fills',
      submitted_to_broker: false,
      can_submit_orders: false,
      symbol: null,
      source_import_run_ids: ['import-run-1'],
      broker_event_count: 4,
      fill_count: 2,
      fills: [
        {
          event_id: 'broker-buy-600519',
          symbol: '600519',
          side: 'buy',
        },
        {
          event_id: 'broker-sell-000001',
          symbol: '000001',
          side: 'sell',
        },
      ],
      limitations: ['This query reads staged broker fill evidence only.'],
    },
  }).fetchMock;

  const automation = await screen.findByTestId('decision-automation-cockpit');

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/broker-gateway/fills/query',
      expect.anything(),
    );
  });
  expect(automation.textContent).toContain('Staged fill polling');
  expect(automation.textContent).toContain('2 staged fills');
  expect(automation.textContent).toContain('4 broker evidence events');
  expect(automation.textContent).toContain('600519');
  expect(automation.textContent).toContain('000001');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('links staged fill evidence to execution reconciliation review without ledger controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    brokerFillsQueryResponse: {
      schema_version: 'karkinos.broker_gateway.v1',
      gateway_id: 'staged_broker_evidence',
      status: 'available',
      query_scope: 'staged_broker_fills',
      submitted_to_broker: false,
      can_submit_orders: false,
      symbol: null,
      source_import_run_ids: ['import-run-1'],
      broker_event_count: 4,
      fill_count: 2,
      fills: [
        {
          event_id: 'broker-buy-600519',
          symbol: '600519',
          side: 'buy',
        },
        {
          event_id: 'broker-sell-000001',
          symbol: '000001',
          side: 'sell',
        },
      ],
      limitations: ['This query reads staged broker fill evidence only.'],
    },
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 3,
        open_item_count: 2,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-1',
            item_status: 'awaiting_broker_evidence',
            suggested_action: 'import_broker_statement_or_update_order',
            gateway_event_count: 1,
            broker_event_count: 0,
            detail:
              'Manual broker ticket exists; broker evidence is still required.',
          },
        ],
      },
    ],
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain(
    'Staged fills ready for reconciliation review',
  );
  expect(automation.textContent).toContain(
    '2 staged fills can be compared with execution reconciliation before any ledger update.',
  );
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('ledger-sync');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces read-only broker order query evidence for reconciliation items', async () => {
  const { fetchMock } = renderDecisionCockpit({
    locale: 'en',
    brokerOrderQueryResponse: {
      schema_version: 'karkinos.broker_gateway.v1',
      gateway_id: 'manual_ticket',
      status: 'query_ready',
      query_scope: 'local_audit_and_staged_broker_evidence',
      submitted_to_broker: false,
      can_submit_orders: false,
      oms_order: {
        order_id: 'OMS-1',
        symbol: '600519',
        status: 'manual_ticket_created',
        payload: {
          execution_mode: 'manual_confirmation',
          does_not_submit_broker_order: true,
        },
      },
      gateway_event_count: 2,
      gateway_events: [{ event_type: 'manual_ticket_created' }],
      staged_broker_fill_count: 1,
      staged_broker_fills: [
        {
          event_id: 'broker-buy-600519',
          symbol: '600519',
          quantity: '100',
        },
      ],
      limitations: [
        'This query reads local Karkinos facts and staged broker evidence only.',
      ],
    },
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 3,
        open_item_count: 2,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-1',
            item_status: 'awaiting_broker_evidence',
            suggested_action: 'import_broker_statement_or_update_order',
            gateway_event_count: 1,
            broker_event_count: 0,
            detail:
              'Manual broker ticket exists; broker evidence is still required.',
          },
        ],
      },
    ],
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/broker-gateway/orders/OMS-1/query',
      expect.anything(),
    );
  });
  expect(automation.textContent).toContain('Read-only order query');
  expect(automation.textContent).toContain('OMS-1');
  expect(automation.textContent).toContain('Manual ticket created');
  expect(automation.textContent).toContain('2 gateway events');
  expect(automation.textContent).toContain('1 staged broker fill');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces broker trade cost evidence before ledger updates without controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 1,
        open_item_count: 1,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-COST-1',
            item_status: 'broker_evidence_available',
            suggested_action: 'review_broker_evidence_match',
            gateway_event_count: 1,
            broker_event_count: 1,
            detail:
              'Broker evidence matches the manual ticket and needs review.',
            payload: {
              broker_trade_cost_summary: {
                source: 'staged_broker_evidence',
                event_count: 1,
                event_ids: ['broker-buy-600519'],
                currency: 'CNY',
                gross_amount: '168800.00',
                fee: '5.00',
                tax: '0',
                transfer_fee: '0',
                net_amount: '-168805.00',
                review_required_before_ledger_update: true,
                does_not_mutate_production_ledger: true,
              },
            },
          },
        ],
      },
    ],
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Broker cost evidence');
  expect(automation.textContent).toContain('1 broker event');
  expect(automation.textContent).toContain('Gross amount');
  expect(automation.textContent).toContain('¥168,800.00');
  expect(automation.textContent).toContain('Fee / tax');
  expect(automation.textContent).toContain('¥5.00 / ¥0.00');
  expect(automation.textContent).toContain('Transfer fee');
  expect(automation.textContent).toContain('Net amount');
  expect(automation.textContent).toContain('-¥168,805.00');
  expect(automation.textContent).toContain('Review before ledger update');
  expect(automation.textContent).toContain('No ledger mutation');
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('ledger-sync');
  expect(automation.textContent).not.toContain('Apply fill');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces manual execution evidence before ledger updates without controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 1,
        open_item_count: 1,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-MANUAL-1',
            item_status: 'manual_execution_recorded',
            suggested_action:
              'review_manual_execution_and_import_broker_statement',
            gateway_event_count: 2,
            broker_event_count: 0,
            detail:
              'Manual execution evidence is recorded; import broker statement or explicitly review before any ledger update.',
            payload: {
              manual_execution_evidence_summary: {
                source: 'broker_gateway_event',
                event_count: 1,
                event_ids: [42],
                preview_fingerprint:
                  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                fill_price: '1688.00',
                quantity: '100',
                gross_amount: '168800.00',
                fee: '5.00',
                tax: '0.00',
                transfer_fee: '0.00',
                net_cash_impact: '-168805.00',
                ledger_entry_amount: '-168805.00',
                review_required_before_ledger_update: true,
                requires_operator_ledger_save: true,
                submitted_to_broker: false,
                does_not_mutate_oms: true,
                does_not_mutate_production_ledger: true,
              },
            },
          },
        ],
      },
    ],
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Manual execution evidence');
  expect(automation.textContent).toContain('1 gateway event');
  expect(automation.textContent).toContain('Manual execution recorded');
  expect(automation.textContent).toContain(
    'Review manual execution and import broker statement',
  );
  expect(automation.textContent).toContain('Preview fingerprint');
  expect(automation.textContent).toContain(
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  );
  expect(automation.textContent).toContain('Fill price');
  expect(automation.textContent).toContain('¥1,688.00');
  expect(automation.textContent).toContain('Quantity');
  expect(automation.textContent).toContain('100');
  expect(automation.textContent).toContain('Gross amount');
  expect(automation.textContent).toContain('¥168,800.00');
  expect(automation.textContent).toContain('Fee / tax');
  expect(automation.textContent).toContain('¥5.00 / ¥0.00');
  expect(automation.textContent).toContain('Net cash impact');
  expect(automation.textContent).toContain('-¥168,805.00');
  expect(automation.textContent).toContain('Ledger draft');
  expect(automation.textContent).toContain('Review before ledger update');
  expect(automation.textContent).toContain('Operator ledger save required');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).toContain('No OMS mutation');
  expect(automation.textContent).toContain('No ledger mutation');
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('ledger-sync');
  expect(automation.textContent).not.toContain('Apply fill');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces manual versus broker reconciliation differences without controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 1,
        open_item_count: 1,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-MISMATCH-1',
            item_status: 'broker_evidence_mismatch',
            suggested_action: 'review_broker_evidence_mismatch',
            gateway_event_count: 2,
            broker_event_count: 1,
            detail:
              'Manual execution evidence differs from staged broker trade evidence.',
            payload: {
              manual_broker_comparison: {
                schema_version: 'karkinos.manual_broker_comparison.v1',
                status: 'mismatch',
                mismatch_reasons: [
                  'manual_execution_fill_price_mismatch',
                  'manual_execution_fee_mismatch',
                  'manual_execution_net_amount_mismatch',
                ],
                compared_values: {
                  quantity: { manual: '100', broker: '100' },
                  fill_price: { manual: '1688.00', broker: '1689.00' },
                  fee: { manual: '5.00', broker: '6.00' },
                  net_amount: {
                    manual: '-168805.20',
                    broker: '-168906.20',
                  },
                },
                review_required_before_ledger_update: true,
                does_not_recommend_automatic_ledger_update: true,
                does_not_mutate_oms: true,
                does_not_mutate_production_ledger: true,
              },
            },
          },
        ],
      },
    ],
  });

  const comparison = await screen.findByTestId(
    'manual-broker-comparison-evidence',
  );

  expect(comparison.textContent).toContain(
    'Manual / broker evidence comparison',
  );
  expect(comparison.textContent).toContain('Manual and broker evidence differ');
  expect(comparison.textContent).toContain('Fill price');
  expect(comparison.textContent).toContain('Manual record: ¥1,688.00');
  expect(comparison.textContent).toContain('Broker evidence: ¥1,689.00');
  expect(comparison.textContent).toContain('Fee');
  expect(comparison.textContent).toContain('Manual record: ¥5.00');
  expect(comparison.textContent).toContain('Broker evidence: ¥6.00');
  expect(comparison.textContent).toContain('Review before ledger update');
  expect(comparison.textContent).toContain(
    'No automatic ledger recommendation',
  );
  expect(comparison.textContent).toContain('No OMS mutation');
  expect(comparison.textContent).toContain('No ledger mutation');
  expect(comparison.textContent).not.toContain('Sync ledger');
  expect(comparison.textContent).not.toContain('Apply fill');
  expect(comparison.textContent).not.toContain('Submit broker order');
  expect(comparison.textContent).not.toContain('Cancel broker order');
});

test('surfaces manual execution alert evidence in automation cockpit without controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    automationCockpitResponse: {
      schema_version: 'karkinos.automation_cockpit.v1',
      broker_submission_enabled: false,
      automation_status: {
        schema_version: 'karkinos.automation_status.v1',
        default_execution_mode: 'paper_shadow',
        broker_submission_enabled: false,
        manual_confirmation_required: true,
        kill_switch_enabled: false,
        latest_runs: [],
        limitations: ['Live broker submission is disabled by default.'],
      },
      gateways: [],
      open_alert_count: 1,
      open_alerts: [
        {
          id: 9,
          alert_type: 'execution_reconciliation',
          severity: 'warning',
          status: 'open',
          title: 'Manual execution evidence requires reconciliation review',
          detail:
            'Manual execution evidence is recorded; import broker statement or explicitly review before any ledger update. no broker order was submitted; OMS and production ledger remain unchanged.',
          created_at: '2026-07-06T09:45:00+08:00',
          payload: {
            item_status: 'manual_execution_recorded',
            suggested_action:
              'review_manual_execution_and_import_broker_statement',
            requires_manual_review: true,
            does_not_submit_broker_order: true,
            does_not_mutate_oms: true,
            does_not_mutate_production_ledger: true,
            manual_execution_evidence_summary: {
              source: 'broker_gateway_event',
              event_count: 1,
              event_ids: [42],
              preview_fingerprint:
                'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
              fill_price: '1688.00',
              quantity: '100',
              gross_amount: '168800.00',
              fee: '5.00',
              tax: '0.00',
              transfer_fee: '0.00',
              net_cash_impact: '-168805.00',
              ledger_entry_amount: '-168805.00',
              review_required_before_ledger_update: true,
              requires_operator_ledger_save: true,
              submitted_to_broker: false,
              does_not_mutate_oms: true,
              does_not_mutate_production_ledger: true,
            },
          },
        },
      ],
      recent_runs: [],
      promotion_states: [],
      execution_reconciliation_open_items: [],
      limitations: ['Cockpit summary is read-only.'],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain(
    'Manual execution evidence requires reconciliation review',
  );
  expect(automation.textContent).toContain(
    'Manual execution evidence is recorded',
  );
  expect(automation.textContent).toContain('Preview fingerprint');
  expect(automation.textContent).toContain(
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  );
  expect(automation.textContent).toContain('Gross amount');
  expect(automation.textContent).toContain('¥168,800.00');
  expect(automation.textContent).toContain('Net cash impact');
  expect(automation.textContent).toContain('-¥168,805.00');
  expect(automation.textContent).toContain('Review before ledger update');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).toContain('No OMS mutation');
  expect(automation.textContent).toContain('No ledger mutation');
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('ledger-sync');
  expect(automation.textContent).not.toContain('Apply fill');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
});

test('surfaces failed paper shadow automation recovery action without execution controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    automationCockpitResponse: {
      schema_version: 'karkinos.automation_cockpit.v1',
      broker_submission_enabled: false,
      automation_status: {
        schema_version: 'karkinos.automation_status.v1',
        default_execution_mode: 'paper_shadow',
        broker_submission_enabled: false,
        manual_confirmation_required: true,
        kill_switch_enabled: false,
        latest_runs: [],
        limitations: ['Live broker submission is disabled by default.'],
      },
      gateways: [],
      open_alert_count: 1,
      open_alerts: [
        {
          id: 11,
          alert_type: 'automation_run',
          severity: 'warning',
          status: 'open',
          title: 'Paper/shadow automation run failed',
          detail:
            'Automation run market_session:2026-07-02:abc ended with paper_shadow_failed. Paper/shadow run failed; no broker order was submitted.',
          created_at: '2026-07-02T10:05:00+08:00',
          payload: {
            run_status: 'paper_shadow_failed',
            run_type: 'market_session',
            execution_mode: 'paper_shadow',
            input_fingerprint: 'abc123def456',
            idempotency_key: 'market_session:2026-07-02:abc123def456',
            input_snapshot: {
              schema_version: 'karkinos.daily_trading_plan.v1',
              order_intent_count: 1,
              source_decision: 'buy',
              input_fingerprint: 'abc123def456',
            },
            retry_state: {
              attempt: 2,
              max_attempts: 2,
              retryable: true,
              previous_attempts: 1,
            },
            suggested_action: 'inspect_failed_paper_shadow_run',
            requires_manual_review: true,
            retry_recommended: true,
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
        },
      ],
      recent_runs: [],
      promotion_states: [],
      execution_reconciliation_open_items: [],
      limitations: ['Cockpit summary is read-only.'],
    },
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain(
    'Next: inspect failed paper/shadow run',
  );
  expect(automation.textContent).toContain(
    'Paper/shadow automation run failed',
  );
  expect(automation.textContent).toContain('inspect failed paper/shadow run');
  expect(automation.textContent).toContain(
    'Input snapshot: 1 order intent · Source Buy · Fingerprint abc123def456',
  );
  expect(automation.textContent).toContain(
    'Rerun key: market_session:2026-07-02:abc123def456',
  );
  expect(automation.textContent).toContain('Retry 2/2; previous attempts 1');
  expect(automation.textContent).toContain('Manual review required');
  expect(automation.textContent).toContain('Retry recommended');
  expect(automation.textContent).toContain('No broker submission');
  expect(automation.textContent).toContain('No ledger mutation');
  expect(automation.textContent).not.toContain('input_snapshot');
  expect(automation.textContent).not.toContain('idempotency_key');
  expect(automation.textContent).not.toContain('Submit broker order');
  expect(automation.textContent).not.toContain('Cancel broker order');
  expect(automation.textContent).not.toContain('Sync ledger');
});

test('surfaces latest execution reconciliation run without ledger mutation controls', async () => {
  renderDecisionCockpit({
    locale: 'en',
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 3,
        open_item_count: 2,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
        items: [
          {
            item_id: 1,
            order_id: 'OMS-1',
            item_status: 'awaiting_broker_evidence',
            suggested_action: 'import_broker_statement_or_update_order',
            gateway_event_count: 1,
            broker_event_count: 0,
            detail:
              'Manual broker ticket exists; broker evidence is still required.',
          },
        ],
      },
    ],
  });

  const automation = await screen.findByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('Execution reconciliation');
  expect(automation.textContent).toContain('Open items');
  expect(automation.textContent).toContain('2 open of 3');
  expect(automation.textContent).toContain('OMS-1');
  expect(automation.textContent).toContain('Awaiting broker evidence');
  expect(automation.textContent).toContain(
    'Import broker statement or update order',
  );
  expect(automation.textContent).toContain(
    'Manual broker ticket exists; broker evidence is still required.',
  );
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('Apply fill');
  expect(automation.textContent).not.toContain('Submit broker order');
});

test('loads execution reconciliation item detail when the recent run list is summary-only', async () => {
  const { fetchMock } = renderDecisionCockpit({
    locale: 'en',
    executionReconciliationRunsResponse: [
      {
        run_id: 'execution-reconciliation:2026-07-06',
        run_date: '2026-07-06',
        status: 'open_items',
        item_count: 3,
        open_item_count: 2,
        created_at: '2026-07-06T09:45:00+08:00',
        payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
      },
    ],
    executionReconciliationRunDetailResponse: {
      run_id: 'execution-reconciliation:2026-07-06',
      run_date: '2026-07-06',
      status: 'open_items',
      item_count: 3,
      open_item_count: 2,
      created_at: '2026-07-06T09:45:00+08:00',
      payload: { schema_version: 'karkinos.execution_reconciliation.v1' },
      items: [
        {
          item_id: 1,
          order_id: 'OMS-DETAIL-1',
          item_status: 'gateway_action_missing',
          suggested_action: 'create_manual_ticket_or_cancel',
          gateway_event_count: 0,
          broker_event_count: 0,
          detail: 'OMS order is confirmed but no gateway action is recorded.',
        },
      ],
    },
  });

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes(
          '/api/execution-reconciliation/runs/execution-reconciliation%3A2026-07-06',
        ),
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(
      screen.getByTestId('decision-automation-cockpit').textContent,
    ).toContain('OMS-DETAIL-1'),
  );
  const automation = screen.getByTestId('decision-automation-cockpit');

  expect(automation.textContent).toContain('OMS-DETAIL-1');
  expect(automation.textContent).toContain('Gateway action missing');
  expect(automation.textContent).toContain('Create manual ticket or cancel');
  expect(automation.textContent).toContain(
    'OMS order is confirmed but no gateway action is recorded.',
  );
  expect(automation.textContent).not.toContain('Sync ledger');
  expect(automation.textContent).not.toContain('Apply fill');
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
