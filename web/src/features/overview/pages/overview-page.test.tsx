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
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  expect(fetch.mock.calls.map(([url]) => String(url)).sort()).toEqual(
    [
      '/api/portfolio/state',
      '/api/portfolio/equity-curve/series?range=1m',
      '/api/decision/today',
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
  expect(screen.getByText('Return unavailable')).toBeVisible();
  expect(screen.getByText(/37.6%/)).toBeVisible();
  expect(screen.queryByText('Current Drawdown')).not.toBeInTheDocument();
});

test('shows the canonical daily strategy recommendation separately from operations attention', async () => {
  installFetch();
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  expect(within(recommendation).getByText('今日决策与操作')).toBeVisible();
  expect(
    await within(recommendation).findByText('今日账户操作：无操作'),
  ).toBeVisible();
  expect(recommendation).toHaveTextContent('未产生账户操作信号');
  expect(recommendation).toHaveTextContent('只读建议');
  expect(within(recommendation).getByRole('link')).toHaveAttribute(
    'href',
    '/decision',
  );
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
    expect(recommendation).toHaveTextContent('今日账户建议证据不可用'),
  );
  const blockers = within(recommendation).getByTestId(
    'overview-decision-blockers',
  );
  expect(blockers).toHaveTextContent('行情数据');
  expect(blockers).toHaveTextContent('刷新或确认当前行情证据');
  expect(blockers).toHaveTextContent('账户事实');
  expect(blockers).toHaveTextContent('刷新账户事实快照');
  expect(blockers).toHaveTextContent('研究策略');
  expect(blockers).toHaveTextContent('NOT READY');
  expect(blockers).toHaveTextContent(
    '当前没有已晋级到 Paper Shadow 的证据策略',
  );
  expect(
    within(blockers).getByRole('link', {
      name: '进入证据研究并完成策略晋级',
    }),
  ).toHaveAttribute('href', '/ai-research');
  expect(blockers).not.toHaveTextContent('valuation_snapshot_not_complete');
});

test('shows a manual-review strategy action without implying automatic execution', async () => {
  const plan = tradingPlanFixture();
  plan.manual_ready_count = 1;
  plan.order_intent_count = 1;
  plan.account_action_recommendation!.status = 'manual_review_required';
  plan.account_action_recommendation!.actions = [
    {
      action_id: 'action-1',
      symbol: '600519',
      asset_class: 'stock',
      side: 'buy',
      target_weight: 0.12,
      estimated_quantity: 100,
      submission_status: 'manual_review_required',
    },
  ];
  installFetch(accountFixture(), false, plan);
  renderPage('zh');
  const recommendation = await screen.findByTestId(
    'overview-strategy-recommendation',
  );
  await waitFor(() =>
    expect(recommendation).toHaveTextContent('1 个交易计划意图待复核'),
  );
  expect(recommendation).toHaveTextContent('买入候选');
  expect(recommendation).toHaveTextContent('600519');
  expect(recommendation).toHaveTextContent('数量 100');
  expect(recommendation).toHaveTextContent('不创建或提交券商订单');
});

test('latest completed-session data on a verified non-trading day is usable with an empty attention queue', async () => {
  installFetch();
  renderPage();
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    'Data as of 09/11 · Market closed · Current valuation usable',
  );
  const queue = screen.getByTestId('overview-today-queue');
  expect(within(queue).getByText('0')).toBeVisible();
  expect(
    within(queue).getByText('No items need your attention today.'),
  ).toBeVisible();
  expect(within(queue).queryByRole('link')).not.toBeInTheDocument();
  expect(
    screen.queryByText(
      /Evidence complete|Evidence degraded|Cached quotes|Broker disabled/,
    ),
  ).not.toBeInTheDocument();
});

test('a later failed refresh does not contradict a usable published valuation', async () => {
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
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    'Current valuation usable',
  );
  expect(screen.getAllByRole('status')).toHaveLength(1);
  const details = screen.getByTestId('overview-data-details');
  expect(details).not.toHaveAttribute('open');
  expect(within(details).getByText('Latest refresh failed')).not.toBeVisible();
  await userEvent.click(within(details).getByText('Data details'));
  expect(within(details).getByText('Latest refresh failed')).toBeVisible();
  expect(within(details).getByText('synthetic-snapshot')).toBeVisible();
  expect(screen.getByTestId('overview-data-status')).not.toHaveTextContent(
    'review',
  );
});

test.each(['degraded', 'unavailable'] as const)(
  'renders canonical %s valuation without normalizing a closed market',
  async (status) => {
    const state = accountFixture();
    state.overview.valuation_usability = status;
    state.overview.pricing_as_of = '2026-09-10';
    installFetch(state);
    renderPage();
    const banner = await screen.findByTestId('overview-data-status');
    expect(banner).toHaveTextContent(
      status === 'degraded'
        ? 'Valuation evidence needs review'
        : 'Valuation unavailable',
    );
    expect(banner).not.toHaveTextContent('Current valuation usable');
  },
);

test('confirmed open-end fund NAV is instrument aware with no realtime or cache claim', async () => {
  const state = accountFixture();
  state.snapshot.positions[0].quote_status = 'cached';
  installFetch(state);
  renderPage();
  await screen.findByTestId('overview-summary');
  for (const label of screen.getAllByTestId('position-pricing-fixture-fund'))
    expect(label).toHaveTextContent('Published NAV · 09/11');
  expect(screen.queryByText('Live quote')).not.toBeInTheDocument();
  expect(screen.queryByText(/27h|Cached quote/)).not.toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /合成基金/ })[0]).toHaveAttribute(
    'href',
    '/portfolio/fixture-fund',
  );
});

test.each(['estimated_nav', 'nav_pending'] as const)(
  'keeps fund %s visibly non-authoritative',
  async (kind) => {
    const state = accountFixture();
    state.snapshot.positions[0].pricing_kind = kind;
    state.snapshot.positions[0].pricing_authority = 'non_authoritative';
    installFetch(state);
    renderPage();
    await screen.findByTestId('overview-summary');
    expect(
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent(
      kind === 'estimated_nav' ? 'Estimated NAV' : 'Confirmed NAV unavailable',
    );
    expect(
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent('Unconfirmed data');
  },
);

test('attention unavailable cannot masquerade as zero actions', async () => {
  const state = accountFixture();
  state.overview.attention_status = 'unavailable';
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('Attention status unavailable')).toBeVisible();
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
  await userEvent.click(screen.getByText('Data details'));
  expect(screen.getByText(/Could not refresh this view/)).toBeVisible();
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

test('Chinese presentation preserves published NAV and compact no-action semantics', async () => {
  installFetch();
  renderPage('zh');
  expect(
    await screen.findByRole('heading', { name: '投资总览' }),
  ).toBeVisible();
  expect(await screen.findByText('今天没有需要处理的事项')).toBeVisible();
  expect(
    screen.getAllByTestId('position-pricing-fixture-fund')[0],
  ).toHaveTextContent('已公布净值 · 09/11');
});

test('shows valuation coverage when current holdings are not fully evidence-gated', async () => {
  const state = accountFixture();
  state.snapshot.valuation_status = 'degraded';
  state.overview.valuation_usability = 'degraded';
  state.snapshot.valuation_lanes = [
    {
      asset_class: 'stock',
      status: 'degraded',
      quote_count: 2,
      complete_quote_count: 1,
      review_required_quote_count: 1,
      blocker_statuses: ['stale'],
    },
    {
      asset_class: 'fund',
      status: 'degraded',
      quote_count: 3,
      complete_quote_count: 0,
      review_required_quote_count: 3,
      blocker_statuses: ['stale'],
    },
  ];

  installFetch(state);
  renderPage('zh');
  const coverage = await screen.findByTestId('overview-valuation-coverage');
  expect(coverage).toHaveTextContent('估值覆盖');
  expect(coverage).toHaveTextContent('股票');
  expect(coverage).toHaveTextContent('1/2');
  expect(coverage).toHaveTextContent('基金');
  expect(coverage).toHaveTextContent('0/3');
  expect(coverage).toHaveTextContent('3 个标的待补证据');
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
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent(
      authority === 'missing'
        ? 'Price evidence missing'
        : authority === 'conflicting'
          ? 'Conflicting price evidence'
          : 'Pricing unverified',
    );
    expect(screen.getByTestId('overview-data-status')).toHaveTextContent(
      'Valuation unavailable',
    );
  },
);

test('stock closing prices use the close basis in the primary as-of summary', async () => {
  const state = accountFixture();
  state.snapshot.positions[0] = {
    ...state.snapshot.positions[0],
    asset_class: 'stock',
    instrument_type: 'stock',
    pricing_kind: 'session_close',
  };
  installFetch(state);
  renderPage('zh');
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    '数据截至 09/11 收盘 · 市场休市 · 当前估值可用',
  );
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
  const pricing = screen.getAllByTestId('position-pricing-fixture-fund')[0];
  expect(pricing).toHaveTextContent('Published NAV · 09/11');
  expect(pricing).not.toHaveTextContent(/update required|older than expected/);
  expect(screen.getByTestId('overview-data-status')).toHaveTextContent(
    'Current valuation usable',
  );
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
  expect(within(queue).getByText('Attention status unavailable')).toBeVisible();
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
  expect(drivers).toHaveTextContent('上一交易日主要影响');
  expect(drivers).toHaveTextContent('合成基金');
  expect(drivers).toHaveTextContent('-¥314.51');
});
