import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { OverviewPage } from './router';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const portfolioSnapshot = {
  cash: 76000,
  total_equity: 101000,
  total_deposits: 100000,
  positions: [],
  allocation: [],
  allocation_grouped: [],
  valuation_snapshot_id: 'valuation-overview-fixture',
  valuation_as_of: '2026-02-10T15:00:00+08:00',
  ledger_cutoff_id: 42,
  ledger_fingerprint: 'ledger-overview-fixture',
  quote_set_fingerprint: 'quotes-overview-fixture',
};

const currentHoldingMarketEvidenceReview = {
  schema_version: 'karkinos.current_holding_market_evidence_review.v1',
  status: 'no_current_holdings',
  next_manual_action: 'none',
  current_holding_count: 0,
  confirmed_holding_count: 0,
  review_required_count: 0,
  fund_nav_review_count: 0,
  estimated_review_count: 0,
  stale_or_cached_review_count: 0,
  missing_or_error_review_count: 0,
  unknown_status_review_count: 0,
  refreshable_symbols: [],
  items: [],
  source_blockers: [],
  review_fingerprint: `sha256:${'a'.repeat(64)}`,
  valuation_snapshot_id: 'valuation-overview-fixture',
  valuation_as_of: '2026-02-10T15:00:00+08:00',
  valuation_trade_date: '2026-02-10',
  valuation_policy: 'karkinos.persisted_valuation.v4',
  valuation_status: 'complete',
  ledger_cutoff_id: 42,
  ledger_fingerprint: 'ledger-overview-fixture',
  quote_set_fingerprint: 'quotes-overview-fixture',
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  runtime_connector_query_performed: false,
  database_writes_performed: false,
  does_not_mutate_oms: true,
  does_not_mutate_production_ledger: true,
  does_not_mutate_risk: true,
  does_not_mutate_kill_switch: true,
  does_not_change_capital_authority: true,
  authorizes_execution: false,
};

const explainability = {
  equity_bridge: [],
  recent_drivers: [],
  positions: [],
  timeline: [
    {
      date: '2026-02-10',
      equity: 101000,
      delta: 800,
      external_flow: 200,
      market_pnl: 600,
      events: [],
    },
  ],
};

const ledgerEntries = [
  {
    id: 2,
    entry_type: 'trade_buy',
    timestamp: '2026-01-15T03:04:56+00:00',
    amount: 3250,
    symbol: '600003',
    display_name: '示例制造',
    direction: 'buy',
    quantity: 200,
    price: 16.25,
    commission: 5,
    asset_class: 'stock',
    note: '合成测试流水：示例制造 600003 买入，按本地费率规则计费',
    source: 'manual',
    source_ref: 'manual-stock-a-20260115-100000',
    created_at: null,
  },
  {
    id: 1,
    entry_type: 'trade_buy',
    timestamp: '2026-01-12T06:33:41+00:00',
    amount: 1850,
    symbol: '600002',
    display_name: '示例材料',
    direction: 'buy',
    quantity: 100,
    price: 18.5,
    commission: 5,
    asset_class: 'stock',
    note: '合成测试流水：示例材料 买入，按本地费率规则计费',
    source: 'manual',
    source_ref: 'manual-stock-b-20260112-103000',
    created_at: null,
  },
];

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
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
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

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function installOverviewFetchMock(
  overviewOverrides: Record<string, unknown> = {},
  {
    snapshot = portfolioSnapshot,
    activityEntries = ledgerEntries,
    pendingOrders = [],
    marketQuotes = [
      {
        symbol: '000001',
        asset_class: 'index',
        display_name: 'Shanghai Composite',
        name: 'Shanghai Composite',
        timestamp: '2026-02-10T14:30:00+08:00',
        price: 3120.5,
        quote_status: 'live',
        quote_source: 'fixture',
        quote_age_seconds: 60,
        stale_reason: null,
        last_refresh_attempt: null,
        last_refresh_error: null,
        daily_change_pct: 0.012,
      },
      {
        symbol: '399001',
        asset_class: 'index',
        display_name: 'Shenzhen Component',
        name: 'Shenzhen Component',
        timestamp: '2026-02-10T14:30:00+08:00',
        price: 9870.2,
        quote_status: 'live',
        quote_source: 'fixture',
        quote_age_seconds: 60,
        stale_reason: null,
        last_refresh_attempt: null,
        last_refresh_error: null,
        daily_change_pct: -0.004,
      },
    ],
    decision = {
      lane: 'daily',
      decision_date: '2026-02-10',
      generated_at: '2026-02-10T10:00:00+08:00',
      decision: 'no_action',
      requires_manual_confirmation: false,
      summary: {
        candidate_count: 0,
        ready_for_manual_confirmation_count: 0,
      },
      candidates: [],
      no_action_reasons: ['no_pending_action_tasks'],
      limitations: [],
    },
    tradingPlan = {
      schema_version: 'karkinos.daily_trading_plan.v1',
      plan_date: '2026-02-10',
      generated_at: '2026-02-10T10:00:00+08:00',
      source_decision: 'no_action',
      conclusion_status: 'no_manual_action',
      primary_target: 'decision',
      candidate_pool_count: 0,
      manual_ready_count: 0,
      order_intent_count: 0,
      blocked_count: 0,
      available_cash: 76000,
      total_equity: 101000,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      order_intents: [],
      blockers: [],
      limitations: [
        'Order intents are manual-confirmation previews, not broker submissions.',
      ],
    },
    operationsToday = {
      schema_version: 'karkinos.operations_today.v1',
      operations_date: '2026-02-10',
      generated_at: '2026-02-10T10:00:00+08:00',
      conclusion_status: 'healthy',
      primary_target: 'decision',
      health: {
        total: 8,
        pass: 6,
        degraded: 0,
        blocked: 0,
        manual_action_required: 0,
        skipped: 2,
      },
      subsystems: [
        {
          id: 'paper_shadow',
          status: 'skipped',
          tone: 'neutral',
          target: 'paper-shadow',
          last_run_at: null,
          next_action: 'none',
          limitations: [],
          detail_status: 'not_required',
        },
      ],
      daily_plan: {
        candidate_pool_count: 0,
        manual_ready_count: 0,
        blocked_count: 0,
        order_intent_count: 0,
        conclusion_status: 'no_manual_action',
      },
      paper_shadow: {
        status: 'not_required',
        run_id: null,
        order_intent_count: 0,
        simulated_order_count: 0,
        simulated_fill_count: 0,
        divergence_reviewed_count: 0,
        divergence_status: 'not_required',
        next_manual_review_step: 'none',
        last_run_at: null,
        orders: [],
      },
      limitations: [
        'Operations summary is read-only and does not submit broker orders.',
      ],
    },
    strategyContribution = {
      schema_version: 'karkinos.account_strategy_contribution.v2',
      strategy_id: 'dual_ma',
      contribution_status: 'evidence_bound_from_posted_fills',
      evidence_binding_status: 'bound',
      next_manual_action: 'review_evidence_bound_strategy_contribution',
      blockers: [],
      linked_fill_count: 2,
      ledger_posted_fill_count: 2,
      unposted_linked_fill_count: 0,
      unattributed_fill_count: 0,
      gross_realized_pnl: 0,
      gross_unrealized_pnl: 128.5,
      total_commission: 5,
      total_slippage: 1.5,
      total_tax: 0,
      net_contribution: 122,
      unattributed_account_pnl: null,
      manual_unattributed_pnl: null,
      cash_flow_pnl: null,
      missing_valuation_symbols: [],
      valuation_snapshot_id: 'valuation-overview-fixture',
      valuation_status: 'complete',
      valuation_scope_status: 'complete',
      ledger_cutoff_id: 42,
      contribution_fingerprint: 'contribution-overview-fixture',
      evidence_refs: [
        'fill:FILL-1',
        'fill:FILL-2',
        'ledger_entry:41',
        'ledger_entry:42',
        'valuation_snapshot:valuation-overview-fixture',
      ],
      persisted_facts_only: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
      limitations: [
        'Contribution is estimated only from linked strategy fills and latest local quotes.',
      ],
    },
    marketEvidenceReview = currentHoldingMarketEvidenceReview,
  }: {
    snapshot?: Record<string, unknown>;
    activityEntries?: unknown[];
    pendingOrders?: unknown[];
    marketQuotes?: unknown[];
    decision?: Record<string, unknown>;
    tradingPlan?: Record<string, unknown>;
    operationsToday?: Record<string, unknown>;
    strategyContribution?: Record<string, unknown>;
    marketEvidenceReview?: Record<string, unknown>;
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/portfolio/overview')) {
      return jsonResponse({
        total_equity: 101000,
        available_cash: 76000,
        total_deposits: 100000,
        positions_count: 0,
        unrealized_pnl: 1000,
        realized_pnl: 0,
        cash_ratio: 0.75,
        valuation_timestamp: '2026-02-10T15:00:00+08:00',
        quote_status: 'live',
        today_pnl: 29,
        today_pnl_breakdown: {
          stocks: 33,
          funds: -4,
          others: 0,
          total: 29,
        },
        today_contributors: [
          {
            symbol: 'SYN999',
            name: '后端权威贡献',
            display_name: '后端权威贡献',
            asset_class: 'stock',
            today_change: 33,
            today_change_pct: 0.012,
            quote_status: 'live',
          },
        ],
        current_drawdown: 0.0459,
        daily_operations: {
          candidate_pool_count: 0,
          evidence_passed_count: 0,
          risk_checked_count: 0,
          risk_passed_count: 0,
          risk_blocked_count: 0,
          paper_shadow_review_count: 0,
          manual_ready_count: 0,
          pending_manual_order_count: 0,
          execution_record_count: 0,
          fill_record_count: 0,
          ledger_review_count: 0,
          execution_exception_count: 0,
          default_execution_mode: 'manual_confirmation',
          broker_bridge_status: 'disabled',
          conclusion_status: 'no_manual_action',
          primary_target: 'decision',
          limitations: [],
        },
        ...overviewOverrides,
      });
    }
    if (url.includes('/api/portfolio/market-evidence-review')) {
      return jsonResponse(marketEvidenceReview);
    }
    if (url.endsWith('/api/portfolio')) {
      return jsonResponse(snapshot);
    }
    if (url.includes('/api/portfolio/live-holdings')) {
      return jsonResponse({
        groups: [
          {
            asset_class: 'stock',
            label: '股票',
            total_market_value: 12000,
            total_today_change: 98.85,
            total_since_buy_pnl: 480,
            items: [
              {
                symbol: '600003',
                name: '示例制造',
                display_name: '示例制造',
                asset_class: 'stock',
                quantity: 200,
                avg_cost: 16.25,
                market_value: 3400,
                latest_price: 17,
                quote_timestamp: '2026-02-10T14:30:00+08:00',
                since_buy_pnl: 150,
                since_buy_pnl_pct: 0.046,
                today_change: 98.85,
                today_change_pct: 0.03,
                baseline_price: 16.5,
                baseline_timestamp: '2026-02-10T09:30:00+08:00',
                baseline_source: 'previous_close',
                quote_status: 'live',
              },
            ],
          },
          {
            asset_class: 'fund',
            label: '基金',
            total_market_value: 9000,
            total_today_change: -10.68,
            total_since_buy_pnl: 120,
            items: [
              {
                symbol: '019999',
                name: '示例稳健混合C',
                display_name: '示例稳健混合C',
                asset_class: 'fund',
                quantity: 3000,
                avg_cost: 1,
                market_value: 3000,
                latest_price: 1,
                quote_timestamp: '2026-02-10T15:00:00+08:00',
                since_buy_pnl: -25,
                since_buy_pnl_pct: -0.008,
                today_change: -10.68,
                today_change_pct: -0.003,
                baseline_price: 1.003,
                baseline_timestamp: '2026-02-10T09:30:00+08:00',
                baseline_source: 'previous_nav',
                quote_status: 'estimated',
                quote_source: 'eastmoney_fund_estimate',
              },
            ],
          },
        ],
      });
    }
    if (url.includes('/api/portfolio/equity-curve/series')) {
      return jsonResponse([
        {
          timestamp: '2026-02-09T15:00:00+08:00',
          total: 100200,
          stocks: 24200,
          funds: 0,
          others: 0,
          cash: 76000,
        },
        {
          timestamp: '2026-02-10T15:00:00+08:00',
          total: 101000,
          stocks: 25000,
          funds: 0,
          others: 0,
          cash: 76000,
        },
      ]);
    }
    if (url.includes('/api/portfolio/risk-workspace')) {
      return jsonResponse({
        metrics: [],
        drawdown: {
          current_drawdown: 0,
          max_drawdown: 0,
          latest_equity: 101000,
          peak_equity: 101000,
          peak_timestamp: null,
          trough_timestamp: null,
        },
        drawdown_series: [],
        exposure_buckets: [],
        concentration: [],
      });
    }
    if (url.includes('/api/ledger/entries')) {
      return jsonResponse(activityEntries);
    }
    if (url.includes('/api/trading/orders')) {
      return jsonResponse(pendingOrders);
    }
    if (url.includes('/api/decision/today')) {
      return jsonResponse(decision);
    }
    if (url.includes('/api/decision/trading-plan')) {
      return jsonResponse(tradingPlan);
    }
    if (url.includes('/api/operations/today')) {
      return jsonResponse(operationsToday);
    }
    if (url.includes('/api/market/data-health')) {
      return jsonResponse({
        quotes: marketQuotes,
        market_open: true,
        refresh_policy: 'live',
        provider_status: 'live',
        provider_name: 'akshare',
        provider_configured: true,
        provider_requires_token: false,
        provider_supports_funds: true,
        provider_last_error: null,
        provider_timeout_seconds: null,
        next_action: null,
        metadata_configured_count: 0,
        source_health: 'live',
        cache_age_seconds: null,
        latest_quote_timestamp: null,
        last_refresh_attempt: null,
        last_refresh_error: null,
        stale_symbols_count: 0,
        stale_symbols_sample: [],
      });
    }
    if (url.includes('/api/market/calendar')) {
      return jsonResponse({
        schema_version: 'karkinos.market_calendar.v1',
        exchange: 'SSE',
        year: 2026,
        provider: 'fixture',
        status: 'complete',
        trading_day_count: 1,
        closed_day_count: 1,
        source_fingerprint: 'calendar-fixture',
        official_verification_status: 'unverified',
        official_source_url: null,
        official_verified_at: null,
        official_verified_by: null,
        limitations: [],
        days: [
          {
            schema_version: 'karkinos.market_calendar.v1',
            date: '2026-06-26',
            day_type: 'trading_day',
            reason_code: 'trading_day',
            reason: 'Trading day',
            is_trading_day: true,
          },
          {
            schema_version: 'karkinos.market_calendar.v1',
            date: '2026-06-28',
            day_type: 'weekend',
            reason_code: 'weekend',
            reason: 'Weekend',
            is_trading_day: false,
          },
        ],
        updated_at: '2026-06-26T15:30:00+08:00',
      });
    }
    if (url.includes('/api/account-strategy/contribution')) {
      return jsonResponse(strategyContribution);
    }
    if (url.includes('/api/portfolio/explainability')) {
      return jsonResponse(explainability);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderOverviewPage({
  installFetch = true,
}: { installFetch?: boolean } = {}) {
  if (installFetch) {
    installOverviewFetchMock();
  }
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

test('keeps a fully closed asset out of current holdings while retaining sell activity', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {
      positions_count: 0,
      realized_pnl: 296,
    },
    {
      snapshot: {
        cash: 10246,
        total_equity: 10246,
        total_deposits: 10000,
        positions: [],
        allocation: [
          {
            symbol: 'CASH',
            name: '现金',
            weight: 1,
            value: 10246,
            asset_class: 'cash',
          },
        ],
        allocation_grouped: [],
        closed_positions: [
          {
            symbol: '600066',
            name: '宇通客车',
            display_name: '宇通客车',
            asset_class: 'stock',
            quantity: 0,
            available_qty: 0,
            frozen_qty: 0,
            avg_cost: 0,
            market_value: 0,
            unrealized_pnl: 0,
            realized_pnl: 296,
            commission_paid: 4,
          },
        ],
        position_review_items: [],
        realized_pnl_total: 296,
      },
      activityEntries: [
        {
          id: 66,
          entry_type: 'trade_sell',
          timestamp: '2026-07-04T10:00:00+08:00',
          amount: 1100,
          symbol: '600066',
          display_name: '宇通客车',
          direction: 'sell',
          quantity: 100,
          price: 11,
          commission: 1,
          gross_amount: 1100,
          net_cash_impact: 1099,
          asset_class: 'stock',
          note: '最终卖出并清仓',
          source: 'manual',
          source_ref: 'fixture-yutong-final-sell',
          created_at: null,
        },
      ],
    },
  );

  renderOverviewPage({ installFetch: false });

  await screen.findByText(/卖出.*宇通客车.*600066/);
  expect(screen.queryByTestId('position-row-600066')).toBeNull();
  expect(screen.queryByTestId('position-card-600066')).toBeNull();
  expect(
    screen.getByText('当前还没有持仓，先去 Activity 录入交易。'),
  ).toBeTruthy();
});

test('renders the compact return calendar on the overview page', async () => {
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const fetchMock = installOverviewFetchMock();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(await screen.findByText('Performance Analysis')).toBeTruthy();
  expect(
    fetchMock.mock.calls.some(([input]) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();
      return url.includes('/api/portfolio/equity-curve/series?range=all');
    }),
  ).toBe(true);
  const calendar = await screen.findByTestId('return-calendar-card');
  expect(calendar.className).toContain('p-4');
  expect(await screen.findByText('Return calendar')).toBeTruthy();
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(
    await screen.findByRole('button', { name: '2026-02-10 · ¥600.00' }),
  ).toBeTruthy();
  expect(await screen.findByText(/示例材料 600002/)).toBeTruthy();
  expect(await screen.findByText(/示例制造 600003/)).toBeTruthy();
  expect(screen.queryByText(/示例制造 600003 600003/)).toBeNull();
  expect(screen.queryByText(/手工录入持仓/)).toBeNull();
  expect(screen.getAllByText('Stock').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText('Quantity 100')).toBeTruthy();
  expect(screen.getAllByText('Fee ¥5.00').length).toBeGreaterThanOrEqual(2);
  expect(screen.queryByText('stock')).toBeNull();
  expect(
    warnSpy.mock.calls.some(([message]) => {
      return (
        typeof message === 'string' &&
        (message.includes('width(-1)') || message.includes('height(0)'))
      );
    }),
  ).toBe(false);
});

test('splits today pnl into stocks funds and total on overview cards', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-02-10T10:00:00+08:00'));

  renderOverviewPage();

  const metricsRail = await screen.findByTestId('account-metrics-rail');
  expect(within(metricsRail).getByText('Today PnL')).toBeTruthy();
  expect(within(metricsRail).getByText('Stocks')).toBeTruthy();
  expect(within(metricsRail).getByText('Funds')).toBeTruthy();
  expect(within(metricsRail).getByText('Total')).toBeTruthy();
  expect(within(metricsRail).getAllByText('¥33.00').length).toBe(2);
  expect(within(metricsRail).getByText('-¥4.00')).toBeTruthy();
  expect(within(metricsRail).getByText('¥29.00')).toBeTruthy();
  expect(within(metricsRail).getByText('-4.59%')).toBeTruthy();
  expect(within(metricsRail).getByText('Top contributors')).toBeTruthy();
  expect(within(metricsRail).getByText('后端权威贡献')).toBeTruthy();
  expect(within(metricsRail).queryByText('示例稳健混合C')).toBeNull();
});

test('labels overview pnl as latest trading day when today is market closed', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-06-28T10:00:00+08:00'));

  renderOverviewPage();

  const metricsRail = await screen.findByTestId('account-metrics-rail');
  expect(within(metricsRail).getByText('Latest trading-day PnL')).toBeTruthy();
  expect(
    within(metricsRail).getByText(
      'Market is closed today; showing the latest available PnL.',
    ),
  ).toBeTruthy();
  expect(within(metricsRail).queryByText('Today PnL')).toBeNull();
});

test('renders the daily workbench before chart and detail panels', async () => {
  renderOverviewPage();

  const workbench = await screen.findByTestId('overview-daily-workbench');
  const marketPulse = await screen.findByTestId('overview-market-pulse');
  const todayQueue = await screen.findByTestId('overview-today-queue');
  const performanceCard = await screen.findByTestId(
    'overview-performance-card',
  );
  const reviewStrip = await screen.findByTestId('overview-review-strip');

  expect(within(workbench).getByText("Today's to-dos")).toBeTruthy();
  expect(
    within(workbench).getByText('No manual trading action needed today'),
  ).toBeTruthy();
  expect(within(workbench).getByText('Today runbook is healthy')).toBeTruthy();
  expect(within(workbench).getByText('No additional action')).toBeTruthy();
  expect(within(workbench).getByText('Execution status')).toBeTruthy();
  expect(within(workbench).getByText('Review queue')).toBeTruthy();
  expect(
    within(workbench).getByText('Market data and NAV are usable.'),
  ).toBeTruthy();
  expect(
    within(workbench).getByText('No orders awaiting confirmation'),
  ).toBeTruthy();
  expect(
    within(workbench).getByText('Strategy contribution is evidence-linked'),
  ).toBeTruthy();
  expect(screen.queryByTestId('overview-operations-panel')).toBeNull();
  expect(within(workbench).queryByText('Daily workbench')).toBeNull();
  expect(within(workbench).queryByText('Daily operations tower')).toBeNull();
  expect(within(marketPulse).getByText('Market pulse')).toBeTruthy();
  expect(within(marketPulse).getByText('Shanghai Composite')).toBeTruthy();
  expect(within(marketPulse).getByText('Shenzhen Component')).toBeTruthy();
  expect(
    within(marketPulse).getByTestId('market-breadth-heatmap-unavailable')
      .textContent,
  ).toContain('Market heatmap awaiting evidence');
  expect(screen.queryByTestId('today-pnl-heatmap')).toBeNull();
  expect(screen.queryByTestId('overview-holding-movers')).toBeNull();
  expect(
    workbench.compareDocumentPosition(performanceCard) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    marketPulse.compareDocumentPosition(performanceCard) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(workbench.contains(todayQueue)).toBe(true);
  expect(
    performanceCard.compareDocumentPosition(reviewStrip) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(reviewStrip)
      .getByTestId('strategy-contribution-gate-card')
      .getAttribute('data-variant'),
  ).toBe('compact');
});

test('surfaces paper shadow next action in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        source_decision: 'buy',
        conclusion_status: 'manual_confirmation_ready',
        primary_target: 'trading',
        candidate_pool_count: 1,
        manual_ready_count: 1,
        order_intent_count: 1,
        blocked_count: 0,
        available_cash: 76000,
        total_equity: 101000,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        order_intents: [],
        blockers: [],
        limitations: [],
      },
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            next_action: 'run_paper_shadow_daily',
            limitations: [],
            detail_status: 'not_run',
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
          status: 'not_run',
          run_id: 'shadow:2026-02-10',
          order_intent_count: 1,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_run',
          next_manual_review_step: 'run_paper_shadow_daily',
          last_run_at: null,
          orders: [],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');
  expect(
    within(todayQueue).getByText('Today runbook needs manual review'),
  ).toBeTruthy();
  expect(
    within(todayQueue).getByText(
      'Run paper/shadow simulation before manual confirmation',
    ),
  ).toBeTruthy();
  expect(within(todayQueue).getByText('2 manual review')).toBeTruthy();
  expect(
    within(todayQueue)
      .getByRole('link', { name: /Review paper\/shadow simulation/ })
      .getAttribute('href'),
  ).toBe('/trading');
});

test('deduplicates manual-plan review and trusts confirmed quotes over provider diagnostics', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {
      quote_status: 'confirmed',
      stale_reason: 'tushare_fund_nav_permission_denied',
    },
    {
      marketQuotes: [
        ['600066', '宇通客车', 'stock'],
        ['601985', '中国核电', 'stock'],
        ['018125', '永赢先进制造智选混合发起C', 'fund'],
        ['026539', '融通科技臻选混合发起式C', 'fund'],
        ['012710', '华夏核心成长混合C', 'fund'],
      ].map(([symbol, displayName, assetClass]) => ({
        symbol,
        asset_class: assetClass,
        display_name: displayName,
        timestamp: '2026-07-10T15:00:00+08:00',
        price: 1.25,
        quote_status: 'confirmed',
        quote_source: 'market_bar_close',
        quote_age_seconds: null,
        stale_reason:
          assetClass === 'fund' ? 'tushare_fund_nav_permission_denied' : null,
        last_refresh_attempt: '2026-07-10T21:30:00+08:00',
        last_refresh_error:
          assetClass === 'fund' ? 'tushare_fund_nav_permission_denied' : null,
        daily_change_pct: null,
      })),
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-07-10',
        generated_at: '2026-07-12T21:54:00+08:00',
        source_decision: 'rebalance',
        conclusion_status: 'manual_confirmation_ready',
        primary_target: 'trading',
        candidate_pool_count: 5,
        manual_ready_count: 5,
        order_intent_count: 5,
        blocked_count: 0,
        available_cash: 6731.61,
        total_equity: 19973.54,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        order_intents: [
          {
            action_id: 893,
            symbol: '600066',
            side: 'buy',
            estimated_quantity: 100,
            submission_status: 'manual_confirmation_required',
          },
          {
            action_id: 892,
            symbol: '601985',
            side: 'buy',
            estimated_quantity: 300,
            submission_status: 'manual_confirmation_required',
          },
          {
            action_id: 888,
            symbol: '018125',
            side: 'sell',
            estimated_quantity: 502.2539,
            submission_status: 'manual_confirmation_required',
          },
          {
            action_id: 836,
            symbol: '026539',
            side: 'sell',
            estimated_quantity: 442.3704,
            submission_status: 'manual_confirmation_required',
          },
          {
            action_id: 818,
            symbol: '012710',
            side: 'sell',
            estimated_quantity: 898.3131,
            submission_status: 'manual_confirmation_required',
          },
        ],
        blockers: [],
        limitations: [],
      },
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-07-10',
        generated_at: '2026-07-12T21:54:00+08:00',
        conclusion_status: 'manual_action_required',
        primary_target: 'trading',
        health: {
          total: 9,
          pass: 7,
          degraded: 1,
          blocked: 0,
          manual_action_required: 1,
          skipped: 0,
        },
        subsystems: [
          {
            id: 'daily_trading_plan',
            status: 'manual_action_required',
            tone: 'warning',
            target: 'trading',
            last_run_at: '2026-07-12T21:54:00+08:00',
            next_action: 'review_manual_order_intents',
            limitations: [],
            detail_status: 'manual_confirmation_ready',
          },
        ],
        daily_plan: {
          candidate_pool_count: 5,
          manual_ready_count: 5,
          blocked_count: 0,
          order_intent_count: 5,
          conclusion_status: 'manual_confirmation_ready',
        },
        paper_shadow: {
          status: 'within_expectations',
          run_id: 'shadow:2026-07-10:c088bce50bb2',
          order_intent_count: 5,
          simulated_order_count: 5,
          simulated_fill_count: 5,
          divergence_reviewed_count: 5,
          divergence_status: 'within_expectations',
          next_manual_review_step: 'review_manual_confirmation',
          last_run_at: '2026-07-12T21:54:00+08:00',
          orders: [],
        },
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');
  expect(within(todayQueue).getByText('5 个交易计划意图待复核')).toBeTruthy();
  expect(todayQueue.textContent).toContain('买入 · 宇通客车（600066） · 100');
  expect(todayQueue.textContent).toContain('买入 · 中国核电（601985） · 300');
  expect(todayQueue.textContent).toContain(
    '卖出 · 永赢先进制造智选混合发起C（018125） · 502.2539',
  );
  expect(todayQueue.textContent).toContain('另 2 笔待确认');
  expect(within(todayQueue).queryByText('今日待办需要人工复核')).toBeNull();
  expect(within(todayQueue).queryByText('行情或净值需要复核。')).toBeNull();
  expect(within(todayQueue).getByText('行情与净值可用于解读。')).toBeTruthy();
});

test('surfaces paper shadow divergence evidence summary in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            last_run_at: '2026-02-10T10:00:00+08:00',
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
          run_id: 'shadow:2026-02-10:review',
          input_fingerprint: 'review',
          input_snapshot: {
            schema_version: 'karkinos.paper_shadow_run.input_snapshot.v1',
            plan_date: '2026-02-10',
            input_fingerprint: 'review',
            source_decision: 'buy',
            order_intent_count: 1,
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 1,
          divergence_reviewed_count: 0,
          divergence_status: 'review_required',
          next_manual_review_step: 'review_shadow_divergence',
          last_run_at: '2026-02-10T10:00:00+08:00',
          review_queue: [
            {
              review_id: 'shadow:2026-02-10:review:ACTION-1',
              order_intent_ref: 'action:ACTION-1',
              order_id: 'SHADOW-2026-02-10-1',
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
                'paper_order:SHADOW-2026-02-10-1',
                'paper_fill:FILL-2026-02-10-1',
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
                estimated_total_fee: '12.30',
                simulated_fee_tax_cost: '12.45',
                simulated_slippage_cost: '4.50',
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
                'oms_transition:SHADOW-2026-02-10-1:1:staged',
                'oms_transition:SHADOW-2026-02-10-1:2:submitted',
                'oms_transition:SHADOW-2026-02-10-1:3:accepted',
                'oms_transition:SHADOW-2026-02-10-1:4:partially_filled',
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
          divergence_summary: {
            expected_strategy_behavior: {
              expected_order_count: 1,
              symbols: ['600519'],
            },
            execution_comparison: {
              matched_order_count: 1,
              diverged_order_refs: ['paper_shadow_order:SHADOW-2026-02-10-1'],
              simulated_status_counts: { partially_filled: 1 },
            },
            realized_market_context: {
              symbol_count: 1,
              price_basis_counts: { latest_quote: 1 },
            },
            cost_summary: {
              simulated_slippage_cost: '4.50',
              simulated_total_execution_cost: '16.85',
            },
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
          orders: [
            {
              order_id: 'SHADOW-2026-02-10-1',
              symbol: '600519',
              status: 'partially_filled',
              divergence_status: 'diverged',
            },
          ],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook needs manual review'),
  ).toBeTruthy();
  expect(todayQueue.textContent).toContain(
    'Review paper/shadow divergence evidence',
  );
  expect(todayQueue.textContent).toContain(
    'Paper/shadow: 1 order intent, 1 sim order, 1 sim fill',
  );
  expect(todayQueue.textContent).toContain(
    'Input snapshot: 1 order intent · Source Buy · Fingerprint review',
  );
  expect(todayQueue.textContent).toContain(
    'Snapshot safety: No broker submission · No production ledger mutation',
  );
  expect(todayQueue.textContent).toContain(
    'Diverged: Simulation review order · SHADOW-2026-02-10-1',
  );
  expect(todayQueue.textContent).toContain(
    'Review queue: 1 item · Resolve paper/shadow divergence before approval',
  );
  expect(todayQueue.textContent).toContain('Risk Passed · Manual Ready');
  expect(todayQueue.textContent).toContain(
    'Account truth Pass · Cash Sufficient',
  );
  expect(todayQueue.textContent).toContain('Constraints Pass: 2');
  expect(todayQueue.textContent).toContain('Projected fee ¥12.30');
  expect(todayQueue.textContent).toContain('Sim fee/tax ¥12.45');
  expect(todayQueue.textContent).toContain('Queue slippage ¥4.50');
  expect(todayQueue.textContent).toContain('Expected ¥123.45 · Fill ¥123.50');
  expect(todayQueue.textContent).toContain(
    'OMS path: Staged > Submitted > Accepted > Partially Filled',
  );
  expect(todayQueue.textContent).toContain(
    'OMS transition: SHADOW-2026-02-10-1 #4 Partially Filled',
  );
  expect(todayQueue.textContent).toContain('Strategy · dual_ma');
  expect(todayQueue.textContent).toContain(
    'Simulation review order · SHADOW-2026-02-10-1',
  );
  expect(todayQueue.textContent).toContain('Sim slippage: ¥4.50');
  expect(todayQueue.textContent).toContain('No broker submission');
  expect(todayQueue.textContent).not.toContain(
    'karkinos.paper_shadow_run.input_snapshot.v1',
  );
  expect(todayQueue.textContent).not.toContain('review_shadow_divergence');
  expect(todayQueue.textContent).not.toContain('partially_filled');
  expect(todayQueue.textContent).not.toContain('oms_transition:');
  expect(todayQueue.textContent).not.toContain('Submit broker order');
});

test('surfaces terminal paper shadow review reasons in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            last_run_at: '2026-02-10T10:00:00+08:00',
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
          run_id: 'shadow:2026-02-10:expired',
          input_fingerprint: 'expired',
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'review_required',
          next_manual_review_step: 'resolve_shadow_divergence',
          last_run_at: '2026-02-10T10:00:00+08:00',
          review_queue: [
            {
              review_id: 'shadow:2026-02-10:expired:ACTION-1',
              order_intent_ref: 'action:ACTION-1',
              order_id: 'SHADOW-EXPIRED',
              symbol: '600519',
              status: 'expired',
              divergence_status: 'review_required',
              severity: 'warning',
              required_action: 'resolve_shadow_divergence',
              reason:
                'Paper/shadow order expired; review terminal simulation reason before manual confirmation.',
              terminal_status: 'expired',
              terminal_reason: 'paper_session_closed',
              terminal_oms_transition_ref:
                'oms_transition:SHADOW-EXPIRED:4:expired',
              oms_status_path: ['staged', 'submitted', 'accepted', 'expired'],
              oms_transition_refs: [
                'oms_transition:SHADOW-EXPIRED:1:staged',
                'oms_transition:SHADOW-EXPIRED:2:submitted',
                'oms_transition:SHADOW-EXPIRED:3:accepted',
                'oms_transition:SHADOW-EXPIRED:4:expired',
              ],
              oms_transitions: [
                {
                  sequence: 4,
                  from_status: 'accepted',
                  to_status: 'expired',
                  source: 'paper_shadow_daily',
                  reason: 'paper_session_closed',
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
              order_id: 'SHADOW-EXPIRED',
              symbol: '600519',
              status: 'expired',
              divergence_status: 'review_required',
            },
          ],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(todayQueue.textContent).toContain(
    'Terminal outcome: Expired · Paper session closed before fill · OMS transition · SHADOW-EXPIRED #4 Expired',
  );
  expect(todayQueue.textContent).not.toContain('paper_session_closed');
  expect(todayQueue.textContent).not.toContain('terminal_reason');
  expect(todayQueue.textContent).not.toContain('Submit broker order');
});

test('surfaces accepted paper shadow review as manual confirmation handoff', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            id: 'daily_trading_plan',
            status: 'manual_action_required',
            tone: 'warning',
            target: 'trading',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'review_manual_order_intents',
            limitations: [],
            detail_status: 'manual_confirmation_ready',
          },
          {
            id: 'paper_shadow',
            status: 'pass',
            tone: 'success',
            target: 'paper-shadow',
            last_run_at: '2026-02-10T10:05:00+08:00',
            next_action: 'review_manual_confirmation',
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
          run_id: 'shadow:2026-02-10:accepted',
          input_fingerprint: 'accepted',
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 0,
          divergence_reviewed_count: 1,
          divergence_status: 'diverged',
          review_status: 'accepted_for_manual_confirmation',
          reviewed_at: '2026-02-10T10:05:00+08:00',
          reviewer: 'local-operator',
          next_manual_review_step: 'review_manual_confirmation',
          last_run_at: '2026-02-10T10:05:00+08:00',
          manual_handoff: {
            ready: true,
            status: 'ready_after_accepted_review',
            blockers: [],
            required_actions: ['review_manual_confirmation'],
            review_queue_count: 1,
            highest_severity: 'warning',
            review_status: 'accepted_for_manual_confirmation',
            reviewed_at: '2026-02-10T10:05:00+08:00',
            reviewer: 'local-operator',
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
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
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook needs manual review'),
  ).toBeTruthy();
  expect(todayQueue.textContent).toContain('Review manual order confirmation');
  expect(
    within(todayQueue)
      .getByRole('link', { name: /Enter manual confirmation/ })
      .getAttribute('href'),
  ).toBe('/trading');
  expect(todayQueue.textContent).toContain(
    'Manual handoff: Ready after accepted simulation review',
  );
  expect(todayQueue.textContent).toContain('Review queue: 1 item');
  expect(todayQueue.textContent).toContain('No broker submission');
  expect(todayQueue.textContent).toContain('No production ledger mutation');
  expect(todayQueue.textContent).not.toContain('review_manual_confirmation');
  expect(todayQueue.textContent).not.toContain(
    'accepted_for_manual_confirmation',
  );
  expect(todayQueue.textContent).not.toContain('ready_after_accepted_review');
  expect(todayQueue.textContent).not.toContain('resolve_shadow_divergence');
  expect(todayQueue.textContent).not.toContain('Submit broker order');
});

test('surfaces within-expectations paper shadow run as manual confirmation handoff', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            id: 'daily_trading_plan',
            status: 'manual_action_required',
            tone: 'warning',
            target: 'trading',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'review_manual_order_intents',
            limitations: [],
            detail_status: 'manual_confirmation_ready',
          },
          {
            id: 'paper_shadow',
            status: 'pass',
            tone: 'success',
            target: 'paper-shadow',
            last_run_at: '2026-02-10T10:05:00+08:00',
            next_action: 'review_manual_confirmation',
            limitations: [],
            detail_status: 'within_expectations',
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
          status: 'within_expectations',
          run_id: 'shadow:2026-02-10:within',
          input_fingerprint: 'within',
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 1,
          divergence_reviewed_count: 0,
          divergence_status: 'within_expectations',
          next_manual_review_step: 'review_manual_confirmation',
          last_run_at: '2026-02-10T10:05:00+08:00',
          divergence_summary: {
            cost_summary: {
              simulated_slippage_cost: '0.00',
              simulated_total_execution_cost: '12.35',
            },
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
          orders: [
            {
              order_id: 'SHADOW-WITHIN',
              symbol: '600519',
              status: 'filled',
              divergence_status: 'within_expectations',
            },
          ],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook needs manual review'),
  ).toBeTruthy();
  expect(todayQueue.textContent).toContain('Review manual order confirmation');
  expect(
    within(todayQueue)
      .getByRole('link', { name: /Enter manual confirmation/ })
      .getAttribute('href'),
  ).toBe('/trading');
  expect(todayQueue.textContent).not.toContain('within_expectations');
  expect(todayQueue.textContent).not.toContain('review_manual_confirmation');
  expect(todayQueue.textContent).not.toContain('Submit broker order');
});

test('surfaces failed paper shadow run recovery in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
        subsystems: [
          {
            id: 'paper_shadow',
            status: 'blocked',
            tone: 'danger',
            target: 'paper-shadow',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'inspect_failed_run',
            limitations: [],
            detail_status: 'failed',
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
          status: 'failed',
          run_id: 'shadow:2026-02-10:failed',
          input_fingerprint: 'failed',
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 0,
          divergence_reviewed_count: 1,
          divergence_status: 'failed',
          next_manual_review_step: 'inspect_failed_run',
          last_run_at: '2026-02-10T10:00:00+08:00',
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
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook has blockers'),
  ).toBeTruthy();
  expect(
    within(todayQueue).getByText(
      'Inspect failed paper/shadow run before approval',
    ),
  ).toBeTruthy();
  expect(within(todayQueue).getByText('1 blocked')).toBeTruthy();
  expect(todayQueue.textContent).not.toContain('inspect_failed_run');
});

test('surfaces running paper shadow run as a wait state in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
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
            last_run_at: '2026-02-10T10:00:00+08:00',
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
          run_id: 'shadow:2026-02-10:running',
          input_fingerprint: 'running',
          order_intent_count: 1,
          simulated_order_count: 1,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'running',
          next_manual_review_step: 'wait_for_paper_shadow_run',
          last_run_at: '2026-02-10T10:00:00+08:00',
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
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook has degraded checks'),
  ).toBeTruthy();
  expect(
    within(todayQueue).getByText(
      'Paper/shadow simulation is running; wait for completion',
    ),
  ).toBeTruthy();
  expect(within(todayQueue).getByText('1 degraded')).toBeTruthy();
  expect(todayQueue.textContent).not.toContain('wait_for_paper_shadow_run');
});

test('surfaces failed scheduler run recovery in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        conclusion_status: 'blocked',
        primary_target: 'scheduler',
        health: {
          total: 8,
          pass: 5,
          degraded: 0,
          blocked: 1,
          manual_action_required: 1,
          skipped: 1,
        },
        subsystems: [
          {
            id: 'scheduler',
            status: 'blocked',
            tone: 'danger',
            target: 'scheduler',
            last_run_at: '2026-02-10T10:00:01+08:00',
            next_action: 'inspect_scheduler_failure',
            limitations: [
              'Paper/shadow run failed; no broker order was submitted.',
            ],
            detail_status: 'paper_shadow_failed',
          },
        ],
        attention_items: [
          {
            schema_version: 'karkinos.operations_attention_item.v1',
            subsystem_id: 'scheduler',
            status: 'blocked',
            target: 'scheduler',
            evidence: {
              status: 'paper_shadow_failed',
              observed_at: '2026-02-10T10:00:01+08:00',
            },
            next_action: 'inspect_scheduler_failure',
            resolution_condition:
              'new_recognized_terminal_scheduler_run_required',
            task_fingerprint: 'sha256:scheduler-attention-fixture',
            manual_acknowledgement_clears_status: false,
            read_only_projection: true,
            provider_contacted: false,
            database_writes_performed: false,
            authorizes_execution: false,
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
          status: 'not_run',
          run_id: 'shadow:2026-02-10',
          order_intent_count: 1,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_run',
          next_manual_review_step: 'run_paper_shadow_daily',
          last_run_at: null,
          orders: [],
        },
        scheduler: {
          status: 'paper_shadow_failed',
          run_id: 'market-session:2026-02-10:100001',
          run_type: 'market_session',
          run_date: '2026-02-10',
          execution_mode: 'paper_shadow',
          last_run_at: '2026-02-10T10:00:01+08:00',
          input_fingerprint: 'abc123',
          idempotency_key: 'market_session:2026-02-10:abc123',
          input_snapshot: {
            order_intent_count: 1,
            source_decision: 'buy',
            input_fingerprint: 'abc123',
          },
          retry_state: {
            attempt: 2,
            max_attempts: 2,
            retryable: true,
            previous_attempts: 1,
          },
          error: { type: 'RuntimeError', message: 'fixture' },
          broker_submission_enabled: false,
          does_not_submit_broker_order: true,
          limitations: [
            'Paper/shadow run failed; no broker order was submitted.',
          ],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook has blockers'),
  ).toBeTruthy();
  expect(todayQueue.textContent).toContain(
    'Inspect scheduler failure evidence before manual review',
  );
  expect(todayQueue.textContent).toContain(
    'Run market-session:2026-02-10:100001',
  );
  expect(todayQueue.textContent).toContain(
    'Input snapshot: 1 order intent · Source Buy · Fingerprint abc123',
  );
  expect(todayQueue.textContent).toContain(
    'Rerun key: market_session:2026-02-10:abc123',
  );
  expect(todayQueue.textContent).toContain('Retry 2/2; previous attempts 1');
  expect(todayQueue.textContent).toContain('RuntimeError: fixture');
  expect(todayQueue.textContent).toContain('No broker submission');
  expect(todayQueue.textContent).toContain(
    'Clears when: a new scheduler run reaches a recognized terminal status. Viewing or acknowledging alone does not clear it.',
  );
  expect(todayQueue.textContent).not.toContain('inspect_scheduler_failure');
  expect(todayQueue.textContent).not.toContain(
    'new_recognized_terminal_scheduler_run_required',
  );
  expect(todayQueue.textContent).not.toContain('input_snapshot');
  expect(todayQueue.textContent).not.toContain('idempotency_key');
  expect(todayQueue.textContent).not.toContain('broker order');
});

test('surfaces manual execution reconciliation review in today todos', async () => {
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        conclusion_status: 'manual_action_required',
        primary_target: 'decision',
        health: {
          total: 9,
          pass: 6,
          degraded: 0,
          blocked: 0,
          manual_action_required: 1,
          skipped: 2,
        },
        subsystems: [
          {
            id: 'execution_reconciliation',
            status: 'manual_action_required',
            tone: 'warning',
            target: 'decision',
            last_run_at: '2026-02-10T10:10:00+08:00',
            next_action: 'review_manual_execution_and_import_broker_statement',
            limitations: ['Manual execution evidence is review evidence only.'],
            detail_status: 'manual_execution_recorded:1',
          },
        ],
        daily_plan: {
          candidate_pool_count: 0,
          manual_ready_count: 0,
          blocked_count: 0,
          order_intent_count: 0,
          conclusion_status: 'no_manual_action',
        },
        paper_shadow: {
          status: 'not_required',
          run_id: null,
          order_intent_count: 0,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_required',
          next_manual_review_step: 'none',
          last_run_at: null,
          orders: [],
        },
        execution_reconciliation: {
          status: 'manual_action_required',
          open_item_count: 1,
          manual_execution_review_count: 1,
          next_review_step:
            'review_manual_execution_and_import_broker_statement',
          first_open_item: {
            order_id: 'MANUAL-001',
            item_status: 'manual_execution_recorded',
            suggested_action:
              'review_manual_execution_and_import_broker_statement',
            detail:
              'Manual execution evidence is recorded; import broker statement before ledger update.',
            manual_execution_evidence_summary: {
              preview_fingerprint: 'preview:abc123',
              submitted_to_broker: false,
              does_not_mutate_oms: true,
              does_not_mutate_production_ledger: true,
            },
          },
          does_not_submit_broker_order: true,
          does_not_mutate_oms: true,
          does_not_mutate_production_ledger: true,
          limitations: [
            'Manual execution evidence requires broker statement import before ledger updates.',
          ],
        },
        limitations: [],
      },
    },
  );
  renderOverviewPage({ installFetch: false });

  const todayQueue = await screen.findByTestId('overview-today-queue');

  expect(
    within(todayQueue).getByText('Today runbook needs manual review'),
  ).toBeTruthy();
  expect(todayQueue.textContent).toContain(
    'Review manual execution and import broker statement',
  );
  expect(todayQueue.textContent).toContain('Manual execution: MANUAL-001');
  expect(todayQueue.textContent).toContain('Preview preview:abc123');
  expect(todayQueue.textContent).toContain('No broker submission');
  expect(todayQueue.textContent).toContain('No OMS mutation');
  expect(todayQueue.textContent).toContain('No production ledger mutation');
  expect(todayQueue.textContent).not.toContain(
    'review_manual_execution_and_import_broker_statement',
  );
  expect(todayQueue.textContent).not.toContain('Submit broker order');
  expect(todayQueue.textContent).not.toContain('Cancel broker order');
  expect(todayQueue.textContent).not.toContain('Ledger sync');
});

test('renders daily operations tower without treating 50 candidates as manual work', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock({
    daily_operations: {
      candidate_pool_count: 50,
      evidence_passed_count: 3,
      risk_checked_count: 3,
      risk_passed_count: 3,
      risk_blocked_count: 0,
      paper_shadow_review_count: 50,
      manual_ready_count: 0,
      pending_manual_order_count: 0,
      execution_record_count: 0,
      fill_record_count: 0,
      ledger_review_count: 0,
      execution_exception_count: 0,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      conclusion_status: 'no_manual_action',
      primary_target: 'decision',
      limitations: [],
    },
  });

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  const tower = await screen.findByTestId('daily-operations-tower');
  expect(within(queue).getByText('今日待办')).toBeTruthy();
  expect(within(tower).getByText('执行状态')).toBeTruthy();
  expect(within(queue).queryByText('今日操作塔台')).toBeNull();
  expect(within(tower).getByText('今日无需手动交易')).toBeTruthy();
  expect(within(tower).getByText('候选池')).toBeTruthy();
  expect(within(tower).getByText('50')).toBeTruthy();
  expect(within(tower).getByText('计划意图待复核')).toBeTruthy();
  expect(within(tower).getAllByText('0').length).toBeGreaterThan(0);
  expect(within(tower).getByText('人工确认')).toBeTruthy();
  expect(within(tower).getByText('未启用')).toBeTruthy();
  expect(within(tower).getByText('复核交易计划')).toBeTruthy();
  expect(tower.textContent).not.toContain('50 项待人工确认');
  expect(tower.textContent).not.toContain('50 个待确认');
});

test('uses the canonical operations summary for the daily operations tower', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {
      daily_operations: {
        candidate_pool_count: 50,
        evidence_passed_count: 6,
        risk_checked_count: 6,
        risk_passed_count: 6,
        risk_blocked_count: 0,
        paper_shadow_review_count: 50,
        manual_ready_count: 6,
        pending_manual_order_count: 0,
        execution_record_count: 50,
        fill_record_count: 0,
        ledger_review_count: 0,
        execution_exception_count: 0,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        conclusion_status: 'pending_manual_confirmation',
        primary_target: 'trading',
        limitations: [],
      },
    },
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-07-16',
        generated_at: '2026-07-16T19:30:00+08:00',
        conclusion_status: 'healthy',
        primary_target: 'decision',
        health: {
          total: 10,
          pass: 5,
          degraded: 0,
          blocked: 0,
          manual_action_required: 0,
          skipped: 5,
        },
        subsystems: [],
        daily_operations: {
          candidate_pool_count: 0,
          evidence_passed_count: 0,
          risk_checked_count: 0,
          risk_passed_count: 0,
          risk_blocked_count: 0,
          paper_shadow_review_count: 0,
          manual_ready_count: 0,
          pending_manual_order_count: 0,
          execution_record_count: 50,
          fill_record_count: 0,
          ledger_review_count: 0,
          execution_exception_count: 0,
          default_execution_mode: 'manual_confirmation',
          broker_bridge_status: 'disabled',
          conclusion_status: 'no_manual_action',
          primary_target: 'decision',
          limitations: [],
        },
        daily_plan: {
          candidate_pool_count: 0,
          manual_ready_count: 0,
          blocked_count: 0,
          order_intent_count: 0,
          conclusion_status: 'no_manual_action',
        },
        paper_shadow: {
          status: 'not_required',
          run_id: null,
          order_intent_count: 0,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_required',
          next_manual_review_step: 'none',
          last_run_at: null,
          orders: [],
        },
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const tower = await screen.findByTestId('daily-operations-tower');
  expect(within(tower).getByText('今日无需手动交易')).toBeTruthy();
  expect(tower.textContent).not.toContain('6 项待人工确认');
});

test('routes daily operations tower primary action to Trading for pending manual orders', async () => {
  installOverviewFetchMock({
    daily_operations: {
      candidate_pool_count: 1,
      evidence_passed_count: 1,
      risk_checked_count: 1,
      risk_passed_count: 1,
      risk_blocked_count: 0,
      paper_shadow_review_count: 0,
      manual_ready_count: 1,
      pending_manual_order_count: 1,
      execution_record_count: 1,
      fill_record_count: 0,
      ledger_review_count: 0,
      execution_exception_count: 0,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      conclusion_status: 'pending_manual_confirmation',
      primary_target: 'trading',
      limitations: [],
    },
  });

  renderOverviewPage({ installFetch: false });

  const tower = await screen.findByTestId('daily-operations-tower');
  expect(
    within(tower).getByText('1 item needs manual confirmation'),
  ).toBeTruthy();
  expect(
    within(tower)
      .getByRole('link', { name: 'Enter manual confirmation' })
      .getAttribute('href'),
  ).toBe('/trading');
});

test('keeps plan intents in Decision until an OMS order awaits approval', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock({
    daily_operations: {
      candidate_pool_count: 3,
      evidence_passed_count: 0,
      risk_checked_count: 3,
      risk_passed_count: 3,
      risk_blocked_count: 0,
      paper_shadow_review_count: 0,
      manual_ready_count: 3,
      pending_manual_order_count: 0,
      execution_record_count: 0,
      fill_record_count: 0,
      ledger_review_count: 0,
      execution_exception_count: 0,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      conclusion_status: 'pending_manual_confirmation',
      primary_target: 'trading',
      limitations: [],
    },
  });

  renderOverviewPage({ installFetch: false });

  const tower = await screen.findByTestId('daily-operations-tower');
  expect(within(tower).getByText('3 个交易计划意图待复核')).toBeTruthy();
  expect(within(tower).getByText('计划意图待复核')).toBeTruthy();
  expect(
    within(tower)
      .getByRole('link', { name: '复核交易计划' })
      .getAttribute('href'),
  ).toBe('/decision');
  expect(tower.textContent).not.toContain('3 项待人工确认');
});

test('routes daily operations tower primary action to Risk for risk blockers', async () => {
  installOverviewFetchMock({
    daily_operations: {
      candidate_pool_count: 2,
      evidence_passed_count: 1,
      risk_checked_count: 2,
      risk_passed_count: 1,
      risk_blocked_count: 1,
      paper_shadow_review_count: 1,
      manual_ready_count: 0,
      pending_manual_order_count: 0,
      execution_record_count: 0,
      fill_record_count: 0,
      ledger_review_count: 0,
      execution_exception_count: 0,
      default_execution_mode: 'manual_confirmation',
      broker_bridge_status: 'disabled',
      conclusion_status: 'risk_blocked',
      primary_target: 'risk',
      limitations: [],
    },
  });

  renderOverviewPage({ installFetch: false });

  const tower = await screen.findByTestId('daily-operations-tower');
  expect(within(tower).getByText('1 risk block needs review')).toBeTruthy();
  expect(
    within(tower)
      .getByRole('link', { name: 'View risk reasons' })
      .getAttribute('href'),
  ).toBe('/risk');
});

test('orders overview workbench items by user-facing priority', async () => {
  installOverviewFetchMock(
    {
      quote_status: 'stale',
      stale_reason: 'confirmed_fund_nav_missing_estimate_only',
      refresh_policy: 'cache_only',
    },
    {
      decision: {
        lane: 'daily',
        decision_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        decision: 'buy',
        requires_manual_confirmation: false,
        summary: {
          candidate_count: 1,
          ready_for_manual_confirmation_count: 0,
        },
        candidates: [
          {
            id: 'candidate-1',
            action: 'buy',
            symbol: '600003',
            display_name: '示例制造',
            name: '示例制造',
            strategy_id: 'dual_ma',
            strategy_name: '双均线策略',
            target_weight: 0.2,
            price: 17,
            asset_class: 'stock',
            risk_gate_status: 'not_checked',
            manual_confirmation_status: 'awaiting_risk_gate',
            evidence: {
              strategy: { strategy_id: 'dual_ma' },
              risk_gate: { status: 'not_checked' },
            },
          },
        ],
        no_action_reasons: [],
        limitations: [],
      },
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        source_decision: 'buy',
        conclusion_status: 'no_manual_action',
        primary_target: 'decision',
        candidate_pool_count: 1,
        manual_ready_count: 0,
        order_intent_count: 0,
        blocked_count: 0,
        available_cash: 76000,
        total_equity: 101000,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        order_intents: [],
        blockers: [],
        limitations: [],
      },
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        status: 'review_required',
        next_manual_action: 'review_current_holding_market_evidence',
        current_holding_count: 1,
        review_required_count: 1,
        stale_or_cached_review_count: 1,
        refreshable_symbols: ['600003'],
        items: [{ symbol: '600003' }],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('Handle first')).toBeTruthy();
  expect(within(queue).getByText('Watch today')).toBeTruthy();
  expect(within(queue).getByText('Normal status')).toBeTruthy();

  const text = queue.textContent ?? '';
  expect(text.indexOf('Market data or NAV needs review.')).toBeGreaterThan(-1);
  expect(text.indexOf('Strategy candidate signal')).toBeGreaterThan(-1);
  expect(text.indexOf('No orders awaiting confirmation')).toBeGreaterThan(-1);
  expect(text.indexOf('Market data or NAV needs review.')).toBeLessThan(
    text.indexOf('Strategy candidate signal'),
  );
  expect(text.indexOf('Strategy candidate signal')).toBeLessThan(
    text.indexOf('No orders awaiting confirmation'),
  );
});

test('surfaces strategy candidate signals in the overview workbench', async () => {
  installOverviewFetchMock(
    {},
    {
      decision: {
        lane: 'daily',
        decision_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        decision: 'buy',
        requires_manual_confirmation: false,
        summary: {
          candidate_count: 1,
          ready_for_manual_confirmation_count: 0,
        },
        candidates: [
          {
            id: 'candidate-1',
            action: 'buy',
            symbol: '600003',
            display_name: '示例制造',
            name: '示例制造',
            strategy_id: 'dual_ma',
            strategy_name: '双均线策略',
            target_weight: 0.2,
            price: 17,
            asset_class: 'stock',
            risk_gate_status: 'not_checked',
            manual_confirmation_status: 'awaiting_risk_gate',
            evidence: {
              strategy: { strategy_id: 'dual_ma' },
              risk_gate: { status: 'not_checked' },
            },
          },
        ],
        no_action_reasons: [],
        limitations: [],
      },
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        source_decision: 'buy',
        conclusion_status: 'no_manual_action',
        primary_target: 'decision',
        candidate_pool_count: 1,
        manual_ready_count: 0,
        order_intent_count: 0,
        blocked_count: 0,
        available_cash: 76000,
        total_equity: 101000,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        order_intents: [],
        blockers: [],
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText('Strategy candidate signal')).toBeTruthy();
  expect(within(workbench).getByText('Buy candidate · 示例制造')).toBeTruthy();
  expect(
    within(workbench).getByText('0 plan review · 1 pool · 0 blocked'),
  ).toBeTruthy();
  expect(within(workbench).getByText('Review decision evidence')).toBeTruthy();
});

test('prioritizes daily trading plan cash shortfall on the overview workbench', async () => {
  installOverviewFetchMock(
    {},
    {
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        source_decision: 'buy',
        conclusion_status: 'cash_shortfall',
        primary_target: 'portfolio',
        candidate_pool_count: 1,
        manual_ready_count: 0,
        order_intent_count: 1,
        blocked_count: 1,
        blocker_summary: [
          {
            category: 'portfolio',
            target: 'portfolio',
            count: 1,
            reasons: ['insufficient_cash'],
            sample_symbols: ['600519'],
          },
        ],
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
            fee_breakdown: {},
            risk_gate_status: 'passed',
            manual_confirmation_status: 'ready_for_manual_confirmation',
            submission_status: 'blocked_by_cash_shortfall',
            does_not_submit_broker_order: true,
            evidence_refs: ['decision_action:9'],
          },
        ],
        blockers: [
          {
            action_id: 9,
            symbol: '600519',
            reason: 'insufficient_cash',
            target: 'portfolio',
          },
        ],
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  const firstGroup = await screen.findByTestId('overview-today-queue-first');

  expect(
    within(firstGroup).getByText('Cash shortfall blocks buy preview'),
  ).toBeTruthy();
  expect(
    within(firstGroup).getByText(
      'Review cash allocation before confirming. Shortfall: ¥9,005.10.',
    ),
  ).toBeTruthy();
  expect(
    within(queue).getByText('0 plan review · 1 pool · Portfolio constraints 1'),
  ).toBeTruthy();
});

test('keeps large candidate pools separate from manual-ready work in Chinese', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  const candidateTemplate = {
    id: 'candidate-1',
    action: 'sell',
    symbol: '603659',
    display_name: '璞泰来',
    name: '璞泰来',
    strategy_id: 'dual_ma',
    strategy_name: '双均线策略',
    target_weight: 0,
    price: 17,
    asset_class: 'stock',
    risk_gate_status: 'not_checked',
    manual_confirmation_status: 'awaiting_risk_gate',
    evidence: {
      strategy: { strategy_id: 'dual_ma' },
      risk_gate: { status: 'not_checked' },
    },
  };
  installOverviewFetchMock(
    {},
    {
      decision: {
        lane: 'daily',
        decision_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        decision: 'sell',
        requires_manual_confirmation: false,
        summary: {
          candidate_count: 50,
          ready_for_manual_confirmation_count: 0,
        },
        candidates: Array.from({ length: 50 }, (_, index) => ({
          ...candidateTemplate,
          id: `candidate-${index + 1}`,
          symbol:
            index === 0 ? '603659' : `600${String(index).padStart(3, '0')}`,
        })),
        no_action_reasons: [],
        limitations: [],
      },
      tradingPlan: {
        schema_version: 'karkinos.daily_trading_plan.v1',
        plan_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        source_decision: 'sell',
        conclusion_status: 'no_manual_action',
        primary_target: 'decision',
        candidate_pool_count: 50,
        manual_ready_count: 0,
        order_intent_count: 0,
        blocked_count: 50,
        blocker_summary: [
          {
            category: 'evidence_not_ready',
            target: 'risk',
            count: 50,
            reasons: ['awaiting_risk_gate'],
            sample_symbols: ['603659', '600001', '600002'],
          },
        ],
        available_cash: 76000,
        total_equity: 101000,
        default_execution_mode: 'manual_confirmation',
        broker_bridge_status: 'disabled',
        order_intents: [],
        blockers: [],
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText('今日交易计划需要复核')).toBeTruthy();
  expect(
    within(workbench).getByText(
      '50 个候选尚未通过风控/证据闸门；当前 0 个需要人工确认。',
    ),
  ).toBeTruthy();
  expect(
    within(workbench).getByText('0 意图待复核 · 50 候选池 · 证据未就绪 50'),
  ).toBeTruthy();
  expect(within(workbench).queryByText('50 个候选动作')).toBeNull();
  expect(within(workbench).queryByText('50 个交易计划意图待复核')).toBeNull();
});

test('explains operations blockers when candidates are waiting for risk gate', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        conclusion_status: 'blocked',
        primary_target: 'trading',
        health: {
          total: 8,
          pass: 2,
          degraded: 2,
          blocked: 1,
          manual_action_required: 1,
          skipped: 2,
        },
        subsystems: [
          {
            id: 'daily_trading_plan',
            status: 'blocked',
            tone: 'danger',
            target: 'trading',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'resolve_daily_plan_blockers',
            limitations: [],
            detail_status: 'no_manual_action',
          },
        ],
        attention_items: [
          {
            schema_version: 'karkinos.operations_attention_item.v1',
            subsystem_id: 'daily_trading_plan',
            status: 'blocked',
            target: 'trading',
            evidence: {
              status: 'no_manual_action',
              observed_at: '2026-02-10T10:00:00+08:00',
            },
            next_action: 'resolve_daily_plan_blockers',
            resolution_condition: 'new_daily_plan_without_blockers_required',
            task_fingerprint: 'sha256:daily-plan-attention-fixture',
            manual_acknowledgement_clears_status: false,
            read_only_projection: true,
            provider_contacted: false,
            database_writes_performed: false,
            authorizes_execution: false,
          },
        ],
        daily_plan: {
          candidate_pool_count: 50,
          manual_ready_count: 0,
          blocked_count: 50,
          blocker_summary: [
            {
              category: 'evidence_not_ready',
              target: 'risk',
              count: 50,
              reasons: ['awaiting_risk_gate'],
              sample_symbols: ['603659', '600066', '026539'],
            },
          ],
          order_intent_count: 0,
          conclusion_status: 'no_manual_action',
        },
        paper_shadow: {
          status: 'not_required',
          run_id: null,
          order_intent_count: 0,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_required',
          next_manual_review_step: 'none',
          last_run_at: null,
          orders: [],
        },
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  const firstGroup = await screen.findByTestId('overview-today-queue-first');

  expect(within(firstGroup).getByText('风险闸门待检查')).toBeTruthy();
  expect(
    within(firstGroup).getByText(
      '50 个候选等待风险闸门检查；当前 0 个可人工确认。',
    ),
  ).toBeTruthy();
  expect(within(firstGroup).getByText('50 待检查')).toBeTruthy();
  expect(within(firstGroup).getByText('查看风控原因')).toBeTruthy();
  expect(firstGroup.textContent).toContain(
    '解除条件：新的日度计划不再包含未解决阻断。仅查看或确认不会清除此状态。',
  );
  expect(queue.textContent).not.toContain('今日待办存在阻断');
  expect(queue.textContent).not.toContain('处理日度交易计划阻断项');
  expect(queue.textContent).not.toContain('1 阻断');
});

test('explains operations blockers when candidates are already blocked by risk', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {},
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        conclusion_status: 'blocked',
        primary_target: 'risk',
        health: {
          total: 8,
          pass: 4,
          degraded: 1,
          blocked: 2,
          manual_action_required: 0,
          skipped: 1,
        },
        subsystems: [
          {
            id: 'risk',
            status: 'blocked',
            tone: 'danger',
            target: 'risk',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'review_risk_blocks',
            limitations: [],
            detail_status: '2',
          },
        ],
        daily_plan: {
          candidate_pool_count: 3,
          manual_ready_count: 0,
          blocked_count: 2,
          blocker_summary: [
            {
              category: 'risk_blocked',
              target: 'risk',
              count: 2,
              reasons: [
                'cash reserve would fall below min_cash_reserve',
                'projected position weight exceeds max_position_weight',
              ],
              sample_symbols: ['510300', '600519'],
            },
          ],
          order_intent_count: 0,
          conclusion_status: 'risk_blocked',
        },
        paper_shadow: {
          status: 'not_required',
          run_id: null,
          order_intent_count: 0,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_required',
          next_manual_review_step: 'none',
          last_run_at: null,
          orders: [],
        },
        limitations: [],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  const firstGroup = await screen.findByTestId('overview-today-queue-first');

  expect(within(firstGroup).getByText('风控阻断待复核')).toBeTruthy();
  expect(
    within(firstGroup).getByText(
      '2 个候选被风控阻断：现金缓冲不足、单标的仓位过高；涉及 510300、600519。先复核原因，不进入人工确认。',
    ),
  ).toBeTruthy();
  expect(within(firstGroup).getByText('2 风控阻断')).toBeTruthy();
  expect(within(firstGroup).getByText('查看风控原因')).toBeTruthy();
  expect(
    within(firstGroup)
      .getByRole('link', { name: /风控阻断待复核/ })
      .getAttribute('href'),
  ).toBe('/risk');
  expect(queue.textContent).not.toContain('今日待办存在阻断');
  expect(queue.textContent).not.toContain('复核风控阻断');
});

test('shows missing market pulse move fields as explicit data gaps', async () => {
  installOverviewFetchMock(
    {},
    {
      marketQuotes: [
        {
          symbol: '000001',
          asset_class: 'index',
          display_name: 'Shanghai Composite',
          name: 'Shanghai Composite',
          timestamp: '2026-02-10T14:30:00+08:00',
          price: 3120.5,
          quote_status: 'live',
          quote_source: 'fixture',
          quote_age_seconds: 60,
          stale_reason: null,
          last_refresh_attempt: null,
          last_refresh_error: null,
        },
        {
          symbol: '000300',
          asset_class: 'index',
          display_name: 'CSI 300',
          name: 'CSI 300',
          timestamp: '2026-02-10T14:30:00+08:00',
          price: 3910.2,
          quote_status: 'live',
          quote_source: 'fixture',
          quote_age_seconds: 60,
          stale_reason: null,
          last_refresh_attempt: null,
          last_refresh_error: null,
        },
      ],
    },
  );

  renderOverviewPage({ installFetch: false });

  const marketPulse = await screen.findByTestId('overview-market-pulse');
  expect(within(marketPulse).getByText('Trend unavailable')).toBeTruthy();
  expect(within(marketPulse).getByText('2 index moves missing')).toBeTruthy();
  expect(within(marketPulse).getAllByText('Move missing')).toHaveLength(2);
  expect(within(marketPulse).queryByText('--')).toBeNull();
});

test('keeps user-readable data work items on stale homepage status', async () => {
  installOverviewFetchMock(
    {
      quote_status: 'stale',
      stale_reason: 'confirmed_fund_nav_missing_estimate_only',
      refresh_policy: 'cache_only',
    },
    {
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        status: 'review_required',
        next_manual_action: 'review_current_holding_market_evidence',
        current_holding_count: 1,
        review_required_count: 1,
        fund_nav_review_count: 1,
        refreshable_symbols: ['FUND-A'],
        items: [{ symbol: 'FUND-A' }],
      },
    },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText("Today's to-dos")).toBeTruthy();
  expect(within(workbench).getByText('Review queue')).toBeTruthy();
  expect(
    within(workbench).getByText('Market data or NAV needs review.'),
  ).toBeTruthy();
  expect(within(workbench).getByText('1 fund NAV')).toBeTruthy();
  expect(within(workbench).queryByText('cache_only')).toBeNull();
  expect(
    within(workbench).queryByText('confirmed_fund_nav_missing_estimate_only'),
  ).toBeNull();
});

test('shows the market evidence repair once before an awaiting risk gate', async () => {
  installOverviewFetchMock(
    {
      quote_status: 'stale',
      stale_reason: 'quote_older_than_expected_session',
    },
    {
      operationsToday: {
        schema_version: 'karkinos.operations_today.v1',
        operations_date: '2026-02-10',
        generated_at: '2026-02-10T10:00:00+08:00',
        conclusion_status: 'blocked',
        primary_target: 'market',
        health: {
          total: 8,
          pass: 4,
          degraded: 0,
          blocked: 2,
          manual_action_required: 0,
          skipped: 2,
        },
        subsystems: [
          {
            id: 'market_data',
            status: 'blocked',
            tone: 'danger',
            target: 'market',
            last_run_at: '2026-02-10T10:00:00+08:00',
            next_action: 'review_market_data_freshness',
            limitations: [],
            detail_status: 'partial',
          },
        ],
        daily_plan: {
          candidate_pool_count: 3,
          manual_ready_count: 0,
          blocked_count: 3,
          order_intent_count: 0,
          conclusion_status: 'evidence_not_ready',
          blocker_summary: [
            {
              category: 'evidence_not_ready',
              target: 'risk',
              count: 3,
              reasons: ['awaiting_risk_gate'],
              symbols: ['600519'],
            },
          ],
        },
        paper_shadow: {
          status: 'not_required',
          run_id: null,
          order_intent_count: 0,
          simulated_order_count: 0,
          simulated_fill_count: 0,
          divergence_reviewed_count: 0,
          divergence_status: 'not_required',
          next_manual_review_step: 'none',
          last_run_at: null,
          orders: [],
        },
        limitations: [],
      },
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        status: 'review_required',
        next_manual_action: 'review_current_holding_market_evidence',
        current_holding_count: 1,
        review_required_count: 1,
        stale_or_cached_review_count: 1,
        refreshable_symbols: ['600519'],
        items: [{ symbol: '600519' }],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const firstGroup = await screen.findByTestId('overview-today-queue-first');
  expect(
    within(firstGroup).getByText('Market data or NAV needs review.'),
  ).toBeTruthy();
  expect(within(firstGroup).queryByText('Risk gate checks pending')).toBeNull();
  expect(
    within(firstGroup)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href')?.startsWith('/market')),
  ).toHaveLength(1);
});

test('renders overview ledger cards with shared public ledger formatting', async () => {
  renderOverviewPage();

  const ledgerPanel = await screen.findByText('Latest ledger');
  const ledgerSection = ledgerPanel.closest('div')?.parentElement;
  expect(ledgerSection).toBeTruthy();
  expect(screen.getByText('2 entries')).toBeTruthy();

  expect(await screen.findByText('Buy 示例制造 600003')).toBeTruthy();
  const firstLedgerAmount = await screen.findByTestId(
    'dashboard-ledger-amount-2',
  );
  expect(firstLedgerAmount.className).toContain('whitespace-nowrap');
  expect(firstLedgerAmount.className).toContain('shrink-0');
  expect(screen.queryByText('示例制造 买入，按本地费率规则计费')).toBeNull();
  expect(screen.queryByText('trade_buy')).toBeNull();
  expect(screen.queryByText(/示例制造 600003 600003/)).toBeNull();
  expect(screen.queryByText(/手工录入持仓/)).toBeNull();
});

test('renders pending approvals with instrument names and public side labels', async () => {
  installOverviewFetchMock(
    {},
    {
      pendingOrders: [
        {
          id: 1,
          order_id: 'ORD-OVERVIEW-SIDE',
          timestamp: '2026-06-18T10:00:00+08:00',
          symbol: 'SYN001',
          display_name: '合成样例股票A',
          side: 'broker_special_side',
          order_type: 'limit',
          quantity: 100,
          price: 8.8,
          intent_id: 'INT-1',
          risk_decision_id: 'RISK-1',
          execution_mode: 'manual',
          status: 'pending_confirm',
          payload_json: '{"intent_id":"INT-1","risk_decision_id":"RISK-1"}',
          note: null,
          created_at: '2026-06-18T10:00:00+08:00',
          updated_at: '2026-06-18T10:00:00+08:00',
        },
      ],
    },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(await screen.findByText('合成样例股票A SYN001')).toBeTruthy();
  expect(await screen.findByText('Status needs review')).toBeTruthy();
  expect(screen.queryByText('broker_special_side')).toBeNull();
  expect(screen.queryByText(/^SYN001$/)).toBeNull();
});

test('labels unconfirmed overview valuation status on the total-assets card', async () => {
  installOverviewFetchMock({
    quote_status: 'estimated',
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  const metricsRail = await screen.findByTestId('account-metrics-rail');
  expect(
    within(metricsRail).getByText(/Valuation status: Estimated/),
  ).toBeTruthy();
});

test('shows evidence-gated strategy contribution on overview', async () => {
  renderOverviewPage();

  const reviewStrip = await screen.findByTestId('overview-review-strip');
  expect(reviewStrip.className).toContain('xl:grid-cols-2');
  expect(await screen.findByText('Strategy contribution')).toBeTruthy();
  expect(await screen.findByText('Evidence-linked')).toBeTruthy();
  expect(await screen.findByText('¥122.00')).toBeTruthy();
});

test('treats zero linked strategy fills as a normal evidence-bound state', async () => {
  installOverviewFetchMock(
    {},
    {
      strategyContribution: {
        strategy_id: 'dual_ma',
        contribution_status: 'no_linked_fills',
        evidence_binding_status: 'not_applicable',
        next_manual_action: 'no_action_until_strategy_linked_fill_exists',
        blockers: [],
        strategy_health_status: 'not_applicable',
        strategy_health_reasons: ['no_strategy_linked_fills_yet'],
        linked_fill_count: 0,
        ledger_posted_fill_count: 0,
        unposted_linked_fill_count: 0,
        unattributed_fill_count: 0,
        gross_realized_pnl: null,
        gross_unrealized_pnl: null,
        total_commission: null,
        total_slippage: null,
        total_tax: null,
        net_contribution: null,
        unattributed_account_pnl: null,
        manual_unattributed_pnl: null,
        cash_flow_pnl: null,
        missing_valuation_symbols: [],
        evidence_refs: [],
        limitations: [
          'No linked fills are available for strategy attribution.',
        ],
      },
    },
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(
    within(workbench).getByText('No attributable strategy fills yet'),
  ).toBeTruthy();
  expect(
    within(workbench).queryByText(
      'Strategy contribution needs linked evidence',
    ),
  ).toBeNull();
  expect(
    within(await screen.findByTestId('overview-today-queue-normal')).getByText(
      'No attributable strategy fills yet',
    ),
  ).toBeTruthy();
  expect(workbench.textContent).toContain(
    'No action required: contribution appears only after a production-ledger fill is explicitly linked to strategy evidence.',
  );
  const reviewStrip = await screen.findByTestId('overview-review-strip');
  expect(reviewStrip.className).not.toContain('xl:grid-cols-2');
  expect(screen.queryByTestId('strategy-contribution-gate-card')).toBeNull();
});

test('scopes the homepage data review count to canonical current holdings', async () => {
  installOverviewFetchMock(
    {},
    {
      snapshot: {
        ...portfolioSnapshot,
        positions: [
          {
            symbol: '600003',
            display_name: '示例制造',
            asset_class: 'stock',
            quantity: 200,
            quote_status: 'stale',
            quote_source: 'persisted_cache',
            stale_reason: 'quote_stale',
          },
        ],
      },
      marketQuotes: [
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quote_status: 'stale',
          quote_source: 'persisted_cache',
          stale_reason: 'quote_stale',
        },
        {
          symbol: '600066',
          display_name: 'Closed fixture holding',
          asset_class: 'stock',
          quote_status: 'stale',
          quote_source: 'persisted_cache',
          stale_reason: 'quote_stale',
        },
        {
          symbol: '000001',
          display_name: 'Shanghai Composite',
          asset_class: 'index',
          quote_status: 'stale',
          quote_source: 'persisted_cache',
          stale_reason: 'quote_stale',
        },
      ],
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        status: 'review_required',
        next_manual_action: 'review_current_holding_market_evidence',
        current_holding_count: 1,
        review_required_count: 1,
        stale_or_cached_review_count: 1,
        refreshable_symbols: ['600003'],
        items: [
          {
            symbol: '600003',
            name: '示例制造',
            asset_class: 'stock',
            quantity: 200,
            quote_status: 'stale',
            quote_source: 'persisted_cache',
            quote_timestamp: '2026-02-10T14:30:00+08:00',
            stale_reason: 'quote_stale',
            nav_date: null,
            review_reason: 'quote_stale_or_cached',
            next_manual_action: 'run_explicit_quote_refresh',
            explicit_refresh_eligible: true,
            blocks_authoritative_decisions: true,
          },
        ],
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('1 stale/cache')).toBeTruthy();
  expect(within(queue).getByText('1 holding needs review')).toBeTruthy();
  expect(queue.textContent).toContain(
    'Clears only after newer confirmed evidence produces a complete current-holding projection bound to one consistent valuation snapshot and ledger cutoff.',
  );
  expect(within(queue).queryByText('2 holdings need review')).toBeNull();
  expect(queue.textContent).not.toContain('Closed fixture holding');
});

test('keeps market index diagnostics out of the current-holding review count', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  installOverviewFetchMock(
    {},
    {
      snapshot: {
        ...portfolioSnapshot,
        positions: ['018125', '012710', '026539'].map((symbol) => ({
          symbol,
          display_name: `Fund ${symbol}`,
          asset_class: 'fund',
          quantity: 100,
          quote_status: 'stale',
          quote_source: 'eastmoney_fund_estimate',
          stale_reason: 'confirmed_fund_nav_missing_estimate_only',
        })),
      },
      marketQuotes: ['399001', '399006'].map((symbol) => ({
        symbol,
        display_name: `Index ${symbol}`,
        asset_class: 'index',
        timestamp: null,
        price: null,
        quote_status: 'missing',
        quote_source: null,
        quote_age_seconds: null,
        stale_reason: 'no_real_data_available',
        last_refresh_attempt: null,
        last_refresh_error: null,
      })),
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        status: 'review_required',
        next_manual_action: 'review_current_holding_market_evidence',
        current_holding_count: 3,
        review_required_count: 3,
        fund_nav_review_count: 3,
        refreshable_symbols: ['012710', '018125', '026539'],
        items: ['012710', '018125', '026539'].map((symbol) => ({
          symbol,
          name: `Fund ${symbol}`,
          asset_class: 'fund',
          quantity: 100,
          quote_status: 'confirmed_nav_missing',
          quote_source: 'eastmoney_fund_estimate',
          quote_timestamp: '2026-02-10T15:00:00+08:00',
          stale_reason: 'confirmed_fund_nav_missing_estimate_only',
          nav_date: null,
          review_reason: 'confirmed_nav_missing',
          next_manual_action:
            'wait_for_confirmed_nav_then_run_explicit_refresh',
          explicit_refresh_eligible: true,
          blocks_authoritative_decisions: true,
        })),
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('3 基金净值')).toBeTruthy();
  expect(
    within(queue).queryByText(
      /个指数缺少持久化行情；在 Market 显式刷新并检查失败批次。/,
    ),
  ).toBeNull();
  expect(within(queue).getByText('3 个标的需要确认')).toBeTruthy();
  expect(within(queue).queryByText(/指数行情/)).toBeNull();
});

test('fails closed when the holding review and portfolio snapshot identities drift', async () => {
  installOverviewFetchMock(
    {},
    {
      marketEvidenceReview: {
        ...currentHoldingMarketEvidenceReview,
        valuation_snapshot_id: 'valuation-drifted-fixture',
      },
    },
  );

  renderOverviewPage({ installFetch: false });

  const queue = await screen.findByTestId('overview-today-queue');
  expect(
    within(queue).getByText(
      'Canonical current-holding evidence is unavailable; authoritative interpretation stays blocked.',
    ),
  ).toBeTruthy();
  expect(
    within(queue).queryByText('Market data and NAV are usable.'),
  ).toBeNull();
});

test('keeps the return calendar inside the performance analysis card', async () => {
  renderOverviewPage();

  const performanceCard = await screen.findByTestId(
    'overview-performance-card',
  );
  expect(
    within(performanceCard).getByText('Performance Analysis'),
  ).toBeTruthy();
  expect(within(performanceCard).getByText('Return calendar')).toBeTruthy();
  expect(
    within(performanceCard).getByTestId('return-calendar-month-grid'),
  ).toBeTruthy();
});
