import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type {
  AccountStateResponse,
  DailyTradingPlanResponse,
  DecisionResponse,
} from '../overview-feature-boundary';
import { OverviewPage } from './overview-page';

function accountFixture(): AccountStateResponse {
  return {
    summary: {
      total_equity: 18585.11,
      available_cash: 6979.91,
      total_deposits: 20000,
      positions_count: 1,
      unrealized_pnl: -1400,
      realized_pnl: -14.89,
      cumulative_pnl: -1414.89,
      cumulative_return: null,
      today_pnl: -314.51,
      cash_ratio: 0.376,
      latest_session_date: '2026-09-11',
    },
    snapshot: {
      cash: 6979.91,
      total_equity: 18585.11,
      total_deposits: 20000,
      positions: [
        {
          symbol: 'fixture-fund',
          display_name: '合成基金',
          asset_class: 'fund',
          instrument_type: 'open_end_fund',
          quantity: 100,
          available_qty: 100,
          frozen_qty: 0,
          avg_cost: 10,
          market_value: 900,
          latest_price: 9,
          unrealized_pnl: -100,
          realized_pnl: 0,
          commission_paid: 0,
          quote_status: 'confirmed',
          pricing_kind: 'published_nav',
          pricing_as_of: '2026-09-11',
          pricing_authority: 'authoritative',
          nav_date: '2026-09-11',
          valuation_available: true,
        },
      ],
      allocation: [
        {
          symbol: 'fixture-fund',
          name: '合成基金',
          asset_class: 'fund',
          weight: 0.048,
          value: 900,
        },
      ],
      allocation_grouped: [],
      valuation_snapshot_id: 'synthetic-snapshot',
      valuation_status: 'complete',
      ledger_cutoff_id: 42,
      ledger_fingerprint: 'synthetic-ledger',
      quote_set_fingerprint: 'synthetic-quotes',
      valuation_policy: 'synthetic-policy',
    },
    risks: [],
    next_step: 'Continue observation',
    overview: {
      market_session: {
        status: 'non_trading_day',
        market_date: '2026-09-14',
        calendar_verified: true,
        latest_completed_trade_date: '2026-09-11',
        expected_quote_date: '2026-09-11',
        next_trading_date: '2026-09-14',
        blockers: [],
      },
      valuation_usability: 'usable',
      pricing_as_of: '2026-09-11',
      refresh_health: { status: 'healthy', latest_attempt: null, blockers: [] },
      decision_readiness: 'blocked',
      user_attention: [],
      attention_status: 'available',
    },
  };
}

function tradingPlanFixture(): DailyTradingPlanResponse {
  return {
    schema_version: 'karkinos.decision.daily_trading_plan.v1',
    plan_date: '2026-09-14',
    generated_at: '2026-09-14T08:00:00+08:00',
    source_decision: 'no_action',
    conclusion_status: 'completed_no_action',
    primary_target: 'manual_review',
    candidate_pool_count: 0,
    manual_ready_count: 0,
    order_intent_count: 0,
    blocked_count: 0,
    available_cash: 6979.91,
    total_equity: 18585.11,
    default_execution_mode: 'manual_confirmation',
    broker_bridge_status: 'disabled',
    order_intents: [],
    blockers: [],
    account_action_recommendation: {
      schema_version: 'karkinos.decision.account_action_recommendation.v1',
      decision_date: '2026-09-14',
      status: 'no_action',
      reason_codes: ['promoted_strategy_scan_completed_without_signal'],
      source_action_task_ids: [],
      actions: [],
      promoted_scan: {
        run_id: 'scan-1',
        status: 'completed_no_signal',
        input_fingerprint: 'a'.repeat(64),
        output_fingerprint: 'b'.repeat(64),
        selected_signal_count: 0,
      },
      account_evidence: {
        valuation_snapshot_id: 'synthetic-snapshot',
        ledger_cutoff_id: 42,
        quote_set_fingerprint: 'synthetic-quotes',
        valuation_status: 'complete',
        account_truth_status: 'passed',
        account_qualification_status: 'passed',
        account_positions_evaluated: true,
      },
      read_only: true,
      manual_confirmation_required: true,
      creates_oms_order: false,
      submits_broker_order: false,
      authorizes_execution: false,
      changes_capital_authority: false,
      authority_effect: 'none',
      evidence_fingerprint: 'c'.repeat(64),
    },
    limitations: [],
  };
}

function decisionFixture(): DecisionResponse {
  return {
    lane: 'daily',
    decision_date: '2026-09-14',
    generated_at: '2026-09-14T08:00:00+08:00',
    decision: 'no_action',
    requires_manual_confirmation: false,
    summary: {
      candidate_count: 0,
      risk_blocked_count: 0,
      ready_for_manual_confirmation_count: 0,
      workflow_tasks: [],
    },
    candidates: [],
    no_action_reasons: [],
    limitations: [],
  };
}

const curve = [
  {
    timestamp: '2026-09-10T15:00:00+08:00',
    total: 18899.62,
    stocks: 0,
    funds: 11919.71,
    others: 0,
    cash: 6979.91,
  },
  {
    timestamp: '2026-09-11T15:00:00+08:00',
    total: 18585.11,
    stocks: 0,
    funds: 11605.2,
    others: 0,
    cash: 6979.91,
  },
];

function installFetch(
  state = accountFixture(),
  curveFailure = false,
  tradingPlan = tradingPlanFixture(),
  decision = decisionFixture(),
) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/portfolio/state')) return Response.json(state);
    if (url.includes('/api/portfolio/equity-curve/series'))
      return curveFailure
        ? new Response('unavailable', { status: 503 })
        : Response.json(curve);
    if (url.includes('/api/decision/today')) return Response.json(decision);
    if (url.includes('/api/decision/trading-plan'))
      return Response.json(tradingPlan);
    if (url.includes('/api/portfolio/explainability'))
      return Response.json({
        timeline: [
          {
            date: '2026-09-11',
            equity: 18585.11,
            delta: -314.51,
            external_flow: 0,
            market_pnl: -314.51,
          },
        ],
        positions: [],
      });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function renderPage(locale: 'en' | 'zh' = 'en') {
  window.localStorage.setItem('karkinos.locale', locale);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const result = render(
    <PreferencesProvider>
      <QueryClientProvider client={client}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { ...result, client };
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
    })),
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test('reads one coherent account projection and a separate canonical history', async () => {
  const fetch = installFetch();
  renderPage();
  await screen.findByTestId('overview-summary');
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(fetch.mock.calls.map(([url]) => String(url)).sort()).toEqual(
    [
      '/api/portfolio/state',
      '/api/portfolio/equity-curve/series?range=ytd',
      '/api/decision/trading-plan',
    ].sort(),
  );
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  expect(screen.getByTestId('overview-cumulative-pnl')).toHaveTextContent(
    '-¥1,414.89',
  );
  expect(screen.getByTestId('overview-session-pnl')).toHaveTextContent(
    '-¥314.51',
  );
  expect(
    within(screen.getByTestId('overview-summary')).getByText('¥6,979.91'),
  ).toBeVisible();
  expect(
    within(screen.getByTestId('overview-summary')).getByText('¥20,000.00'),
  ).toBeVisible();
  expect(
    within(screen.getByTestId('overview-summary')).queryByText(
      'Current Drawdown',
    ),
  ).not.toBeInTheDocument();
});

test('shows the canonical daily strategy recommendation separately from operations attention', async () => {
  installFetch();
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  expect(within(recommendation).getByText('最新策略建议')).toBeVisible();
  expect(await within(recommendation).findByText('无操作')).toBeVisible();
  expect(
    within(recommendation).getByRole('link', { name: '查看全部' }),
  ).toHaveAttribute('href', '/decision');
});

test('explains why today has no actionable recommendation when evidence gates block it', async () => {
  const plan = tradingPlanFixture();
  plan.conclusion_status = 'account_truth_blocked';
  plan.account_action_recommendation!.status = 'unavailable';
  plan.account_action_recommendation!.reason_codes = [
    'promoted_strategy_not_configured',
    'valuation_snapshot_not_complete',
    'market_data_not_trusted',
    'account_truth_not_fresh',
  ];
  const decision = decisionFixture();
  decision.summary.workflow_tasks = [
    {
      id: 'data_refresh',
      priority: 10,
      status: 'blocked',
      title: 'Data refresh',
      description: 'Market evidence is stale.',
      required_actions: ['refresh_or_confirm_market_data'],
      blocking_reasons: ['market_data_not_fully_live'],
    },
    {
      id: 'account_truth',
      priority: 20,
      status: 'blocked',
      title: 'Account truth',
      description: 'Account truth is stale.',
      required_actions: ['account_truth_snapshot_stale'],
      blocking_reasons: ['account_truth_snapshot_stale'],
    },
  ];

  installFetch(accountFixture(), false, plan, decision);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() =>
    expect(recommendation).toHaveTextContent('策略建议暂不可用'),
  );
  expect(recommendation).toHaveTextContent('策略建议暂不可用');
  expect(
    within(recommendation).queryByTestId('overview-decision-actions'),
  ).not.toBeInTheDocument();
});

test('shows a read-only portfolio preview when strict execution freshness is blocked', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation!.status = 'blocked';
  plan.account_action_recommendation!.presentation = {
    level: 'portfolio_preview',
    actions: [
      {
        action_id: null,
        symbol: 'fixture-fund',
        display_name: '合成基金',
        asset_class: 'fund',
        side: 'buy',
        target_weight: 0.12,
        estimated_quantity: null,
        submission_status: 'read_only_signal',
      },
    ],
    signal_status: 'ready',
    portfolio_preview_status: 'ready',
    manual_review_status: 'blocked',
    configuration_blockers: [],
    signal_blockers: [],
    portfolio_preview_blockers: [],
    manual_review_blockers: ['account_truth_not_fresh'],
    read_only: true,
    authorizes_execution: false,
  };
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );

  await waitFor(() => expect(recommendation).toHaveTextContent('组合预览'));
  expect(recommendation).toHaveTextContent('买入');
  expect(recommendation).toHaveTextContent('合成基金');
  expect(recommendation).toHaveTextContent('4.8%');
  expect(recommendation).toHaveTextContent('12.0%');
  expect(recommendation).toHaveTextContent(
    '刷新账户事实与行情后可进入人工复核',
  );
  expect(recommendation).not.toHaveTextContent('预计数量');
  expect(
    within(recommendation).queryByRole('link', { name: '复核交易队列' }),
  ).not.toBeInTheDocument();
});

test('shows only strategy direction when account structure is not coherent enough for sizing', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation!.status = 'blocked';
  plan.account_action_recommendation!.presentation = {
    level: 'signal',
    actions: [
      {
        action_id: null,
        symbol: 'fixture-fund',
        display_name: '合成基金',
        asset_class: 'fund',
        side: 'sell',
        target_weight: 0,
        estimated_quantity: null,
        submission_status: 'read_only_signal',
      },
    ],
    signal_status: 'ready',
    portfolio_preview_status: 'blocked',
    manual_review_status: 'blocked',
    configuration_blockers: [],
    signal_blockers: [],
    portfolio_preview_blockers: ['portfolio_preview_unresolved_mismatch'],
    manual_review_blockers: ['account_truth_unresolved_mismatch'],
    read_only: true,
    authorizes_execution: false,
  };
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );

  await waitFor(() => expect(recommendation).toHaveTextContent('策略信号'));
  expect(recommendation).toHaveTextContent('卖出');
  expect(recommendation).toHaveTextContent('合成基金');
  expect(recommendation).toHaveTextContent(
    '当前仅展示策略方向，账户状态确认后再计算仓位与数量',
  );
  expect(recommendation).not.toHaveTextContent('建议仓位');
  expect(recommendation).not.toHaveTextContent('预计数量');
  expect(
    within(recommendation).queryByRole('link', { name: '复核交易队列' }),
  ).not.toBeInTheDocument();
});

test('labels missing strategy promotion as configuration readiness rather than a safety failure', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation!.status = 'unavailable';
  plan.account_action_recommendation!.presentation = {
    level: 'unavailable',
    actions: [],
    signal_status: 'unavailable',
    portfolio_preview_status: 'blocked',
    manual_review_status: 'blocked',
    configuration_blockers: ['promoted_strategy_not_configured'],
    signal_blockers: ['promoted_strategy_not_configured'],
    portfolio_preview_blockers: [],
    manual_review_blockers: ['promoted_strategy_not_configured'],
    read_only: true,
    authorizes_execution: false,
  };
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );

  await waitFor(() =>
    expect(recommendation).toHaveTextContent(
      '尚未配置可用于账户建议的晋级策略',
    ),
  );
  expect(recommendation).not.toHaveTextContent('策略建议暂不可用');
});

test('labels scan with promoted_daily_candidate_strategy_missing as configuration readiness without green indicator', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation!.status = 'blocked';
  plan.account_action_recommendation!.reason_codes = [
    'promoted_daily_candidate_strategy_missing',
  ];
  plan.account_action_recommendation!.presentation = {
    level: 'blocked',
    actions: [],
    signal_status: 'unavailable',
    portfolio_preview_status: 'blocked',
    manual_review_status: 'blocked',
    configuration_blockers: [
      'promoted_daily_candidate_strategy_missing',
      'promoted_strategy_not_configured',
    ],
    signal_blockers: ['promoted_daily_candidate_strategy_missing'],
    portfolio_preview_blockers: [],
    manual_review_blockers: ['promoted_daily_candidate_strategy_missing'],
    read_only: true,
    authorizes_execution: false,
  };
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );

  await waitFor(() =>
    expect(recommendation).toHaveTextContent(
      '尚未配置可用于账户建议的晋级策略',
    ),
  );
  expect(recommendation).not.toHaveTextContent('策略建议暂不可用');
  expect(
    recommendation.querySelector('.bg-\\[var\\(--app-success-indicator\\)\\]'),
  ).toBeNull();
});

test('shows a manual-review strategy action without implying automatic execution', async () => {
  const plan = tradingPlanFixture();
  plan.manual_ready_count = 1;
  plan.order_intent_count = 1;
  plan.account_action_recommendation!.status = 'manual_review_required';
  plan.account_action_recommendation!.actions = [
    {
      action_id: 'action-1',
      symbol: 'fixture-fund',
      display_name: '合成基金',
      asset_class: 'fund',
      side: 'buy',
      target_weight: 0.12,
      estimated_quantity: 25,
      submission_status: 'manual_confirmation_required',
    },
  ];
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() => expect(recommendation).toHaveTextContent('待人工复核'));
  expect(recommendation).toHaveTextContent('最新策略建议');
  expect(recommendation).toHaveTextContent('2026/09/14');
  expect(recommendation).toHaveTextContent('买入');
  expect(recommendation).toHaveTextContent('合成基金');
  expect(recommendation).toHaveTextContent('fixture-fund');
  expect(recommendation).toHaveTextContent('4.8%');
  expect(recommendation).toHaveTextContent('12.0%');
  expect(recommendation).toHaveTextContent('预计数量');
  expect(recommendation).toHaveTextContent('25 份');
  expect(
    within(recommendation).getByRole('link', { name: '复核交易队列' }),
  ).toHaveAttribute('href', '/trading');
  expect(
    within(recommendation).getByRole('link', { name: '查看决策证据' }),
  ).toHaveAttribute('href', '/decision');
});

test('displays detailed buy recommendation with buy price, amounts, fees, and position effect', async () => {
  const plan = tradingPlanFixture();
  plan.manual_ready_count = 1;
  plan.order_intent_count = 1;
  plan.order_intents = [
    {
      action_id: 101,
      symbol: '600519',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.15,
      estimated_price: 1688.0,
      estimated_quantity: 100,
      quantity_basis: 'board_lot_preview',
      estimated_gross_amount: 168800.0,
      estimated_total_fee: 84.4,
      estimated_net_cash_impact: -168884.4,
      available_cash_before: 200000.0,
      available_cash_after: 31115.6,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [
        { id: 'cash_buffer', status: 'passed', target: 'cash_buffer' },
        { id: 'single_symbol_weight', status: 'passed', target: 'portfolio' },
      ],
      position_effect: {
        current_quantity: 0,
        current_avg_cost: null,
        current_market_value: 0,
        estimated_quantity_after: 100,
        estimated_avg_cost_after: 1688.0,
        cost_basis_method: 'weighted_average_preview',
      },
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'manual_confirmation_required',
      submission_status: 'manual_confirmation_required',
      does_not_submit_broker_order: true,
      evidence_refs: [],
    },
  ];
  plan.account_action_recommendation!.status = 'manual_review_required';
  plan.account_action_recommendation!.actions = [
    {
      action_id: 101,
      symbol: '600519',
      display_name: '贵州茅台',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.15,
      estimated_quantity: 100,
      estimated_price: 1688.0,
      estimated_gross_amount: 168800.0,
      estimated_net_cash_impact: -168884.4,
      estimated_total_fee: 84.4,
      submission_status: 'manual_confirmation_required',
    },
  ];

  installFetch(accountFixture(), false, plan);
  renderPage('zh');

  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() => expect(recommendation).toHaveTextContent('待人工复核'));
  expect(recommendation).toHaveTextContent('买入');
  expect(recommendation).toHaveTextContent('贵州茅台');
  expect(recommendation).toHaveTextContent('600519');
  expect(recommendation).toHaveTextContent('建议买入价');
  expect(recommendation).toHaveTextContent('¥1,688.00');
  expect(recommendation).toHaveTextContent('预计数量');
  expect(recommendation).toHaveTextContent('100 股');
  expect(recommendation).toHaveTextContent('预估金额');
  expect(recommendation).toHaveTextContent('¥168,800.00');
  expect(recommendation).toHaveTextContent('资金变动');
  expect(recommendation).toHaveTextContent('-¥168,884.40');
  expect(recommendation).toHaveTextContent('预估费用');
  expect(recommendation).toHaveTextContent('¥84.40');
  expect(recommendation).toHaveTextContent('预估持仓');
  expect(recommendation).toHaveTextContent('0 → 100 股');
  expect(recommendation).toHaveTextContent('预估成本');
  expect(recommendation).toHaveTextContent('新建立仓');
  expect(recommendation).toHaveTextContent('风控通过');
  expect(recommendation).toHaveTextContent('现金充足');
});

test('displays detailed sell recommendation with sell price and net cash inflow', async () => {
  const plan = tradingPlanFixture();
  plan.manual_ready_count = 1;
  plan.order_intent_count = 1;
  plan.order_intents = [
    {
      action_id: 102,
      symbol: 'fixture-fund',
      asset_class: 'fund',
      side: 'sell',
      target_weight: 0.0,
      estimated_price: 2.5,
      estimated_quantity: 1000,
      quantity_basis: 'full_exit',
      estimated_gross_amount: 2500.0,
      estimated_total_fee: 2.5,
      estimated_net_cash_impact: 2497.5,
      available_cash_before: 5000.0,
      available_cash_after: 7497.5,
      cash_status: 'sufficient',
      cash_shortfall: 0,
      constraint_checks: [],
      position_effect: {
        current_quantity: 1000,
        current_avg_cost: 2.0,
        current_market_value: 2500.0,
        estimated_quantity_after: 0,
        estimated_avg_cost_after: null,
        cost_basis_method: 'sell_reduces_position_preview',
      },
      fee_breakdown: {},
      risk_gate_status: 'passed',
      manual_confirmation_status: 'manual_confirmation_required',
      submission_status: 'manual_confirmation_required',
      does_not_submit_broker_order: true,
      evidence_refs: [],
    },
  ];
  plan.account_action_recommendation!.status = 'manual_review_required';
  plan.account_action_recommendation!.actions = [
    {
      action_id: 102,
      symbol: 'fixture-fund',
      display_name: '合成基金',
      asset_class: 'fund',
      side: 'sell',
      target_weight: 0.0,
      estimated_quantity: 1000,
      estimated_price: 2.5,
      submission_status: 'manual_confirmation_required',
    },
  ];

  installFetch(accountFixture(), false, plan);
  renderPage('zh');

  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() => expect(recommendation).toHaveTextContent('待人工复核'));
  expect(recommendation).toHaveTextContent('卖出');
  expect(recommendation).toHaveTextContent('合成基金');
  expect(recommendation).toHaveTextContent('建议卖出价');
  expect(recommendation).toHaveTextContent('¥2.50');
  expect(recommendation).toHaveTextContent('预计数量');
  expect(recommendation).toHaveTextContent('1,000 份');
  expect(recommendation).toHaveTextContent('预估金额');
  expect(recommendation).toHaveTextContent('¥2,500.00');
  expect(recommendation).toHaveTextContent('资金变动');
  expect(recommendation).toHaveTextContent('+¥2,497.50');
  expect(recommendation).toHaveTextContent('预估费用');
  expect(recommendation).toHaveTextContent('¥2.50');
  expect(recommendation).toHaveTextContent('预估持仓');
  expect(recommendation).toHaveTextContent('1,000 → 0 份');
});

test('never surfaces blocked recommendation actions as buy or sell operations', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation!.status = 'blocked';
  plan.account_action_recommendation!.actions = [
    {
      action_id: 'blocked-action',
      symbol: 'fixture-fund',
      display_name: '合成基金',
      asset_class: 'fund',
      side: 'sell',
      target_weight: 0,
      estimated_quantity: 100,
      submission_status: 'blocked_by_market_data',
    },
  ];
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() =>
    expect(recommendation).toHaveTextContent('策略建议暂不可用'),
  );
  expect(
    within(recommendation).queryByTestId('overview-decision-actions'),
  ).not.toBeInTheDocument();
  expect(recommendation).not.toHaveTextContent('卖出');
});

test('verified non-trading-day state stays compact when there is nothing to do', async () => {
  installFetch();
  renderPage();
  await screen.findByTestId('overview-summary');
  expect(screen.queryByTestId('overview-today-queue')).not.toBeInTheDocument();
  expect(screen.queryByTestId('overview-data-status')).not.toBeInTheDocument();
  expect(screen.queryByTestId('overview-data-trust')).not.toBeInTheDocument();
});

test('a later failed refresh does not crowd a usable overview with diagnostics', async () => {
  const state = accountFixture();
  state.overview.refresh_health = {
    status: 'degraded',
    latest_attempt: {
      status: 'failed',
      updated_at: '2026-09-12T09:00:00+08:00',
    },
    blockers: ['synthetic-provider-error'],
  };
  installFetch(state);
  renderPage();
  expect(await screen.findByTestId('overview-summary')).toBeVisible();
  expect(screen.queryByTestId('overview-data-details')).not.toBeInTheDocument();
  expect(
    screen.queryByText('synthetic-provider-error'),
  ).not.toBeInTheDocument();
});

test.each(['degraded', 'unavailable'] as const)(
  'keeps %s valuation diagnostics out of the overview body',
  async (status) => {
    const state = accountFixture();
    state.overview.valuation_usability = status;
    state.overview.pricing_as_of = '2026-09-10';
    installFetch(state);
    renderPage();
    expect(await screen.findByTestId('overview-summary')).toBeVisible();
    expect(
      screen.queryByTestId('overview-data-status'),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId('overview-data-trust')).not.toBeInTheDocument();
  },
);

test('keeps fund pricing evidence out of overview while preserving holding drill-down', async () => {
  const state = accountFixture();
  state.snapshot.positions[0].quote_status = 'cached';
  installFetch(state);
  renderPage();
  await screen.findByTestId('overview-summary');
  expect(
    screen.queryByTestId('position-pricing-fixture-fund'),
  ).not.toBeInTheDocument();
  expect(screen.queryByText('Live quote')).not.toBeInTheDocument();
  expect(screen.queryByText(/27h|Cached quote/)).not.toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /合成基金/ })[0]).toHaveAttribute(
    'href',
    '/portfolio/fixture-fund',
  );
});

test.each(['estimated_nav', 'nav_pending'] as const)(
  'keeps fund %s diagnostics out of overview holdings',
  async (kind) => {
    const state = accountFixture();
    state.snapshot.positions[0].pricing_kind = kind;
    state.snapshot.positions[0].pricing_authority = 'non_authoritative';
    installFetch(state);
    renderPage();
    await screen.findByTestId('overview-summary');
    expect(
      screen.queryByTestId('position-pricing-fixture-fund'),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('overview-holdings-section')).toBeVisible();
  },
);

test('attention unavailable cannot masquerade as zero actions', async () => {
  const state = accountFixture();
  state.overview.attention_status = 'unavailable';
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('To-do status unavailable')).toBeVisible();
  expect(within(queue).queryByText('0')).not.toBeInTheDocument();
  expect(
    within(queue).queryByText('No items need your attention today.'),
  ).not.toBeInTheDocument();
});

test('renders canonical deduplicated actions without rebuilding downstream blockers', async () => {
  const state = accountFixture();
  state.overview.user_attention = [
    {
      schema_version: 'karkinos.operations_attention_item.v1',
      subsystem_id: 'market_data',
      status: 'blocked',
      target: 'market',
      evidence: { status: 'stale', observed_at: null },
      next_action: 'review_current_holding_market_evidence',
      resolution_condition: 'new_complete_market_evidence_required',
      task_fingerprint: 'one-root-cause',
      manual_acknowledgement_clears_status: false,
      read_only_projection: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
    },
  ];
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('1')).toBeVisible();
  expect(within(queue).getAllByRole('link')).toHaveLength(1);
  expect(within(queue).getByRole('link')).toHaveAttribute('href', '/market');
  expect(queue).not.toHaveTextContent('authorizes_execution');
});

test('a failed equity widget preserves the account canvas and holdings', async () => {
  installFetch(accountFixture(), true);
  renderPage();
  await screen.findByText(/Failed to load equity curve/);
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  expect(screen.getByTestId('overview-holdings-section')).toBeVisible();
});

test('a failed account refresh retains the prior coherent financial view', async () => {
  const mock = installFetch();
  const { client } = renderPage();
  await screen.findByTestId('overview-summary');
  mock.mockImplementation(
    async () => new Response('unavailable', { status: 503 }),
  );
  await act(async () => {
    await client.refetchQueries({ queryKey: ['account-state'] });
  });
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  expect(screen.queryByTestId('overview-data-details')).not.toBeInTheDocument();
});

test('range control requests only a supported canonical series range', async () => {
  const mock = installFetch();
  renderPage();
  await screen.findByTestId('equity-range-controls');
  await userEvent.click(screen.getByRole('button', { name: /6M/ }));
  await waitFor(() =>
    expect(mock).toHaveBeenCalledWith(
      '/api/portfolio/equity-curve/series?range=6m',
      expect.anything(),
    ),
  );
});

test('calendar-year control requests year-to-date history from January 1', async () => {
  const mock = installFetch();
  renderPage('zh');
  await screen.findByTestId('equity-range-controls');
  await userEvent.click(screen.getByRole('button', { name: /今年/ }));
  await waitFor(() =>
    expect(mock).toHaveBeenCalledWith(
      '/api/portfolio/equity-curve/series?range=ytd',
      expect.anything(),
    ),
  );
});

test('Chinese presentation keeps zero-action state compact', async () => {
  installFetch();
  renderPage('zh');
  expect(
    await screen.findByRole('heading', { name: '投资总览' }),
  ).toBeVisible();
  await screen.findByTestId('overview-summary');
  expect(screen.queryByTestId('overview-today-queue')).not.toBeInTheDocument();
  expect(
    screen.queryByTestId('position-pricing-fixture-fund'),
  ).not.toBeInTheDocument();
});

test('keeps valuation coverage diagnostics in drill-down pages instead of overview', async () => {
  const state = accountFixture();
  state.snapshot.valuation_status = 'degraded';
  state.overview.valuation_usability = 'degraded';
  installFetch(state);
  renderPage('zh');
  expect(await screen.findByTestId('overview-summary')).toBeVisible();
  expect(
    screen.queryByTestId('overview-valuation-coverage'),
  ).not.toBeInTheDocument();
});

test.each(['missing', 'conflicting', 'unknown'] as const)(
  'preserves %s price authority as explicit unverified evidence',
  async (authority) => {
    const state = accountFixture();
    state.snapshot.positions[0].pricing_authority = authority;
    state.overview.valuation_usability = 'unavailable';
    state.summary.total_equity = null;
    installFetch(state);
    renderPage();
    expect(await screen.findByTestId('overview-total-value')).toHaveTextContent(
      'Awaiting valuation',
    );
    expect(
      screen.queryByTestId('position-pricing-fixture-fund'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('overview-data-status'),
    ).not.toBeInTheDocument();
  },
);

test('stock closing-price metadata stays out of the overview headline', async () => {
  const state = accountFixture();
  state.snapshot.positions[0] = {
    ...state.snapshot.positions[0],
    asset_class: 'stock',
    instrument_type: 'stock',
    pricing_kind: 'session_close',
  };
  installFetch(state);
  renderPage('zh');
  expect(await screen.findByTestId('overview-summary')).toBeVisible();
  expect(screen.queryByTestId('overview-data-status')).not.toBeInTheDocument();
});

test('usable authoritative fund NAV stays published when live-decision quote freshness is blocked', async () => {
  const state = accountFixture();
  state.snapshot.positions[0].quote_status = 'stale';
  state.snapshot.positions[0].stale_reason =
    'quote_older_than_expected_session';
  state.snapshot.positions[0].valuation_available = true;
  state.overview.decision_readiness = 'blocked';
  installFetch(state);
  renderPage();
  await screen.findByTestId('overview-summary');
  expect(
    screen.queryByTestId('position-pricing-fixture-fund'),
  ).not.toBeInTheDocument();
  expect(screen.queryByTestId('overview-data-status')).not.toBeInTheDocument();
});

test('known valuation repair remains actionable when unrelated Operations evidence is unavailable', async () => {
  const state = accountFixture();
  state.overview.user_attention = [
    {
      schema_version: 'karkinos.operations_attention_item.v1',
      subsystem_id: 'market_data',
      status: 'blocked',
      target: 'market',
      evidence: { status: 'stale', observed_at: null },
      next_action: 'review_current_holding_market_evidence',
      resolution_condition: 'new_complete_market_evidence_required',
      task_fingerprint: 'one-root-cause',
      manual_acknowledgement_clears_status: false,
      read_only_projection: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
    },
  ];
  state.overview.attention_status = 'unavailable';
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('--')).toBeVisible();
  expect(within(queue).getByText('To-do status unavailable')).toBeVisible();
  expect(within(queue).getAllByRole('link')).toHaveLength(2);
  expect(
    within(queue).getByRole('link', {
      name: 'Review current holding prices and NAV',
    }),
  ).toHaveAttribute('href', '/market');
  expect(queue).not.toHaveTextContent('authorizes_execution');
});

test('shows previous-session performance contributors from canonical account state', async () => {
  const state = accountFixture();
  state.summary.today_contributors = [
    {
      symbol: 'fixture-fund',
      display_name: '合成基金',
      asset_class: 'fund',
      today_change: -314.51,
    },
  ];
  installFetch(state);
  renderPage('zh');
  const drivers = await screen.findByTestId('overview-performance-drivers');
  expect(drivers).toHaveTextContent('合成基金');
  expect(drivers).toHaveTextContent('-¥314.51');
});

test('toggles between equity curve and return calendar views', async () => {
  const fetchMock = installFetch();
  const user = userEvent.setup();
  renderPage('zh');

  expect(
    await screen.findByTestId('equity-range-controls'),
  ).toBeInTheDocument();
  expect(screen.queryByTestId('return-calendar-card')).not.toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('/api/portfolio/explainability'),
    ),
  ).toBe(false);

  const calendarTab = screen.getByRole('tab', { name: '收益日历' });
  await user.click(calendarTab);

  expect(await screen.findByTestId('return-calendar-card')).toBeInTheDocument();
  expect(screen.queryByTestId('equity-range-controls')).not.toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('/api/portfolio/explainability'),
    ),
  ).toBe(true);

  const curveTab = screen.getByRole('tab', { name: '净值走势' });
  await user.click(curveTab);

  expect(
    await screen.findByTestId('equity-range-controls'),
  ).toBeInTheDocument();
  expect(screen.queryByTestId('return-calendar-card')).not.toBeInTheDocument();
});

test('renders detailed strategy recommendation with buy and sell prices', async () => {
  const plan = tradingPlanFixture();
  plan.account_action_recommendation = {
    schema_version: 'karkinos.decision.account_action_recommendation.v1',
    decision_date: '2026-09-14',
    status: 'manual_review_required',
    reason_codes: ['strategy_action_ready'],
    source_action_task_ids: [],
    actions: [
      {
        action_id: 'act-1',
        symbol: '600519',
        symbol_name: '贵州茅台',
        asset_class: 'stock',
        side: 'buy',
        target_allocation: 0.15,
        target_quantity: 100,
        target_amount: 180050,
        target_price: 1800.5,
        estimated_execution_price: 1800.5,
        limit_price: 1805.0,
        current_quantity: 0,
        post_trade_quantity: 100,
        estimated_net_amount: -180050,
        estimated_commission: 27.01,
        estimated_stamp_duty: 0,
        estimated_total_cost: 27.01,
        reason: 'trend_continuation',
      },
    ],
    promoted_scan: {
      run_id: 'scan-1',
      status: 'completed_with_signals',
      input_fingerprint: 'a'.repeat(64),
      output_fingerprint: 'b'.repeat(64),
      selected_signal_count: 1,
    },
    account_evidence: {
      valuation_snapshot_id: 'synthetic-snapshot',
      ledger_cutoff_id: 42,
      quote_set_fingerprint: 'synthetic-quotes',
      valuation_status: 'complete',
      account_truth_status: 'passed',
      account_qualification_status: 'passed',
      account_positions_evaluated: true,
    },
    presentation: {
      level: 'manual_review',
      actions: [
        {
          action_id: 'act-1',
          symbol: '600519',
          symbol_name: '贵州茅台',
          side: 'buy',
          target_allocation: 0.15,
          target_quantity: 100,
          target_amount: 180050,
          target_price: 1800.5,
          estimated_execution_price: 1800.5,
          limit_price: 1805.0,
          current_quantity: 0,
          post_trade_quantity: 100,
          estimated_net_amount: -180050,
          estimated_commission: 27.01,
          estimated_stamp_duty: 0,
          estimated_total_cost: 27.01,
          reason: 'trend_continuation',
        },
      ],
      blockers: [],
      warnings: [],
    },
    read_only: true,
    manual_confirmation_required: true,
    creates_oms_order: false,
    submits_broker_order: false,
    authorizes_execution: false,
    execution_blocked: false,
    blockers: [],
    limitations: [],
  };
  installFetch(accountFixture(), false, plan);
  renderPage('zh');

  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() => expect(recommendation).toHaveTextContent('待人工复核'));

  expect(recommendation).toHaveTextContent('贵州茅台');
  expect(recommendation).toHaveTextContent('建议买入价');
  expect(recommendation).toHaveTextContent('¥1,800.50');
  expect(recommendation).toHaveTextContent('建议买入');
  expect(recommendation).toHaveTextContent('100 股');
  expect(recommendation).toHaveTextContent('¥180,050.00');
});
