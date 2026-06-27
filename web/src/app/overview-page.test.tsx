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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function installOverviewFetchMock(
  overviewOverrides: Record<string, unknown> = {},
  {
    pendingOrders = [],
  }: {
    pendingOrders?: unknown[];
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
            label: 'A股',
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
    if (url.includes('/api/market/data-health')) {
      return jsonResponse({
        quotes: [],
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
    if (url.includes('/api/account-strategy/contribution')) {
      return jsonResponse({
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
      });
    }
    if (url.includes('/api/portfolio/explainability')) {
      return jsonResponse(explainability);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderOverviewPage() {
  installOverviewFetchMock();
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
    await screen.findByRole('button', { name: '2026-02-10 · CN¥600.00' }),
  ).toBeTruthy();
  expect(await screen.findByText(/示例材料 600002/)).toBeTruthy();
  expect(await screen.findByText(/示例制造 600003/)).toBeTruthy();
  expect(screen.queryByText(/示例制造 600003 600003/)).toBeNull();
  expect(screen.queryByText(/手工录入持仓/)).toBeNull();
  expect(screen.getAllByText('Stock').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText('Quantity 100')).toBeTruthy();
  expect(screen.getAllByText('Fee CN¥5.00').length).toBeGreaterThanOrEqual(2);
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
  renderOverviewPage();

  const metricsRail = await screen.findByTestId('account-metrics-rail');
  expect(within(metricsRail).getByText('Today PnL')).toBeTruthy();
  expect(within(metricsRail).getByText('Stocks')).toBeTruthy();
  expect(within(metricsRail).getByText('Funds')).toBeTruthy();
  expect(within(metricsRail).getByText('Total')).toBeTruthy();
  expect(within(metricsRail).getByText('CN¥98.85')).toBeTruthy();
  expect(within(metricsRail).getByText('-CN¥10.68')).toBeTruthy();
  expect(within(metricsRail).getByText('CN¥88.17')).toBeTruthy();
});

test('renders the daily workbench before chart and detail panels', async () => {
  renderOverviewPage();

  const workbench = await screen.findByTestId('overview-daily-workbench');
  const holdingMovers = await screen.findByTestId('overview-holding-movers');
  const performanceCard = await screen.findByTestId(
    'overview-performance-card',
  );
  const operationsPanel = await screen.findByTestId(
    'overview-operations-panel',
  );
  const reviewStrip = await screen.findByTestId('overview-review-strip');

  expect(within(workbench).getByText('Today to review')).toBeTruthy();
  expect(
    within(workbench).getByText('Market data and NAV are usable.'),
  ).toBeTruthy();
  expect(
    within(workbench).getByText('No orders awaiting confirmation'),
  ).toBeTruthy();
  expect(
    within(workbench).getByText('Strategy contribution is evidence-linked'),
  ).toBeTruthy();
  expect(within(holdingMovers).getByText('Holding movers')).toBeTruthy();
  expect(within(holdingMovers).getByText('示例制造')).toBeTruthy();
  expect(within(holdingMovers).getByText('CN¥98.85')).toBeTruthy();
  expect(
    within(holdingMovers).getAllByText('Open holding detail').length,
  ).toBeGreaterThan(0);
  expect(
    workbench.compareDocumentPosition(performanceCard) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    holdingMovers.compareDocumentPosition(performanceCard) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(within(operationsPanel).getByText('Data status')).toBeTruthy();
  expect(within(operationsPanel).getByText('Quick actions')).toBeTruthy();
  expect(
    within(operationsPanel).getByRole('button', { name: 'Refresh quotes' }),
  ).toBeTruthy();
  expect(
    performanceCard.compareDocumentPosition(operationsPanel) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    operationsPanel.compareDocumentPosition(reviewStrip) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(reviewStrip)
      .getByTestId('strategy-contribution-gate-card')
      .getAttribute('data-variant'),
  ).toBe('compact');
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
  expect(within(workbench).getByText('Today to review')).toBeTruthy();
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

  expect(await screen.findByText('Buy 示例制造 600003')).toBeTruthy();
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

  expect(await screen.findByText('Strategy contribution')).toBeTruthy();
  expect(await screen.findByText('Evidence-linked')).toBeTruthy();
  expect(await screen.findByText('CN¥122.00')).toBeTruthy();
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
