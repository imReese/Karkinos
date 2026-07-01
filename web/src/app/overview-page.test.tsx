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
    strategyContribution = {
      strategy_id: 'dual_ma',
      contribution_status: 'estimated_from_linked_fills',
      linked_fill_count: 2,
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
      evidence_refs: ['fill:FILL-1', 'fill:FILL-2'],
      limitations: [
        'Contribution is estimated only from linked strategy fills and latest local quotes.',
      ],
    },
  }: {
    pendingOrders?: unknown[];
    marketQuotes?: unknown[];
    decision?: Record<string, unknown>;
    strategyContribution?: Record<string, unknown>;
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
    if (url.endsWith('/api/portfolio')) {
      return jsonResponse(portfolioSnapshot);
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
      return jsonResponse(ledgerEntries);
    }
    if (url.includes('/api/trading/orders')) {
      return jsonResponse(pendingOrders);
    }
    if (url.includes('/api/decision/today')) {
      return jsonResponse(decision);
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
  expect(within(tower).getByText('待人工确认')).toBeTruthy();
  expect(within(tower).getAllByText('0').length).toBeGreaterThan(0);
  expect(within(tower).getByText('人工确认')).toBeTruthy();
  expect(within(tower).getByText('未启用')).toBeTruthy();
  expect(within(tower).getByText('查看候选证据')).toBeTruthy();
  expect(tower.textContent).not.toContain('50 项待人工确认');
  expect(tower.textContent).not.toContain('50 个待确认');
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
    },
  );

  renderOverviewPage({ installFetch: false });

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText('Strategy candidate signal')).toBeTruthy();
  expect(within(workbench).getByText('Buy candidate · 示例制造')).toBeTruthy();
  expect(within(workbench).getByText('1 candidate signal')).toBeTruthy();
  expect(within(workbench).getByText('Review decision evidence')).toBeTruthy();
});

test('labels overview candidate totals as signals in Chinese', async () => {
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
    },
  );

  renderOverviewPage({ installFetch: false });

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText('策略候选信号')).toBeTruthy();
  expect(within(workbench).getByText('卖出候选 · 璞泰来')).toBeTruthy();
  expect(within(workbench).getByText('50 个候选信号')).toBeTruthy();
  expect(within(workbench).queryByText('50 个候选动作')).toBeNull();
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
  installOverviewFetchMock({
    quote_status: 'stale',
    stale_reason: 'confirmed_fund_nav_missing_estimate_only',
    refresh_policy: 'cache_only',
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

  const workbench = await screen.findByTestId('overview-daily-workbench');
  expect(within(workbench).getByText("Today's to-dos")).toBeTruthy();
  expect(within(workbench).getByText('Review queue')).toBeTruthy();
  expect(
    within(workbench).getByText('Market data or NAV needs review.'),
  ).toBeTruthy();
  expect(
    within(workbench).getAllByText(
      'Wait for confirmed fund NAV or sync NAV data',
    ).length,
  ).toBeGreaterThan(0);
  expect(within(workbench).queryByText('cache_only')).toBeNull();
  expect(
    within(workbench).queryByText('confirmed_fund_nav_missing_estimate_only'),
  ).toBeNull();
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

test('keeps unsupported strategy contribution as a workbench task instead of a large overview card', async () => {
  installOverviewFetchMock(
    {},
    {
      strategyContribution: {
        strategy_id: 'dual_ma',
        contribution_status: 'no_linked_fills',
        strategy_health_status: 'needs_review',
        strategy_health_reasons: ['linked_fill_evidence_missing'],
        linked_fill_count: 0,
        gross_realized_pnl: 0,
        gross_unrealized_pnl: 0,
        total_commission: 0,
        total_slippage: 0,
        total_tax: 0,
        net_contribution: 0,
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
    within(workbench).getByText('Strategy contribution needs linked evidence'),
  ).toBeTruthy();
  const reviewStrip = await screen.findByTestId('overview-review-strip');
  expect(reviewStrip.className).not.toContain('xl:grid-cols-2');
  expect(screen.queryByTestId('strategy-contribution-gate-card')).toBeNull();
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
