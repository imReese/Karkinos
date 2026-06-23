import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { HoldingDetailPage } from './holding-detail-page';

const position = {
  symbol: '600519',
  quantity: 60,
  available_qty: 55,
  frozen_qty: 5,
  avg_cost: 1500,
  latest_price: 1600,
  market_value: 96000,
  today_change: 240,
  today_change_pct: 0.0025,
  baseline_price: 1596,
  baseline_timestamp: '2026-04-20',
  baseline_source: 'previous_close',
  unrealized_pnl: 6000,
  realized_pnl: 1200,
  commission_paid: 30,
  quote_status: 'stale',
  quote_timestamp: '2026-04-21T14:30:00+08:00',
  quote_source: 'akshare',
  quote_age_seconds: 2_246_400,
  stale_reason: 'market_closed_cache_only',
  refresh_policy: 'cache_only',
};

const longProviderName =
  'tushare_realtime_quote_with_cn_market_fallback_and_manual_reconciliation_provider';
const longStaleReason =
  'quote_older_than_expected_session_because_current_session_realtime_permission_is_limited_and_cached_quote_is_used';

const ledgerEntry = {
  id: 11,
  entry_type: 'trade_buy',
  timestamp: '2026-04-20T10:00:00+08:00',
  amount: 90000,
  symbol: '600519',
  direction: 'buy',
  quantity: 60,
  price: 1500,
  commission: 30,
  gross_amount: 90000,
  net_cash_impact: -90035.1,
  fee_breakdown: {
    commission: '30',
    stamp_tax: '0',
    transfer_fee: '5.10',
    other_fees: '0',
    total_fee: '35.10',
  },
  fee_rule_id: 'manual_configured_commission',
  fee_rule_version: 'account_commission_rate',
  cost_basis_method: 'moving_average_buy_cost',
  asset_class: 'stock',
  note: 'initial allocation',
  source: 'manual',
  source_ref: null,
  created_at: '2026-04-20T10:01:00+08:00',
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installHoldingFetchMock({
  includePosition = true,
  includeLedger = true,
  failCore = false,
  positionOverride = {},
  liveItemOverride = {},
  healthQuoteOverride = {},
  marketHealthOverride = {},
}: {
  includePosition?: boolean;
  includeLedger?: boolean;
  failCore?: boolean;
  positionOverride?: Partial<typeof position> & Record<string, unknown>;
  liveItemOverride?: Record<string, unknown>;
  healthQuoteOverride?: Record<string, unknown>;
  marketHealthOverride?: Record<string, unknown>;
} = {}) {
  const resolvedPosition = { ...position, ...positionOverride };
  const positions = includePosition ? [resolvedPosition] : [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/portfolio/positions')) {
      return failCore
        ? jsonResponse({ detail: 'portfolio unavailable' }, { status: 503 })
        : jsonResponse(positions);
    }
    if (url.includes('/api/portfolio/live-holdings')) {
      return jsonResponse({
        groups: [
          {
            asset_class: 'stock',
            label: 'Stocks',
            total_market_value: 96000,
            total_today_change: 0,
            total_since_buy_pnl: 6000,
            items: includePosition
              ? [
                  {
                    symbol: '600519',
                    name: 'Kweichow Moutai',
                    asset_class: 'stock',
                    quantity: 60,
                    avg_cost: 1500,
                    market_value: 96000,
                    latest_price: 1600,
                    quote_timestamp: '2026-04-21T14:30:00+08:00',
                    since_buy_pnl: 6000,
                    since_buy_pnl_pct: 0.0667,
                    today_change: 240,
                    today_change_pct: 0.0025,
                    baseline_price: 1596,
                    baseline_timestamp: '2026-04-20',
                    baseline_source: 'previous_close',
                    quote_status: 'stale',
                    quote_source: 'akshare',
                    quote_age_seconds: 2_246_400,
                    stale_reason: 'market_closed_cache_only',
                    refresh_policy: 'cache_only',
                    ...liveItemOverride,
                  },
                ]
              : [],
          },
        ],
      });
    }
    if (url.endsWith('/api/portfolio')) {
      return failCore
        ? jsonResponse({ detail: 'snapshot unavailable' }, { status: 503 })
        : jsonResponse({
            cash: 1000,
            total_equity: 97000,
            total_deposits: 90000,
            positions,
            allocation: includePosition
              ? [
                  {
                    symbol: '600519',
                    name: 'Kweichow Moutai',
                    weight: 0.9897,
                    value: 96000,
                    asset_class: 'stock',
                  },
                ]
              : [],
            allocation_grouped: [],
          });
    }
    if (url.includes('/api/portfolio/overview')) {
      return jsonResponse({
        total_equity: 97000,
        available_cash: 1000,
        total_deposits: 90000,
        positions_count: positions.length,
        unrealized_pnl: 6000,
        realized_pnl: 1200,
        cash_ratio: 0.0103,
        valuation_timestamp: '2026-05-16T22:40:00+08:00',
        quote_status: 'stale',
        quote_age_seconds: 2_246_400,
        stale_reason: 'market_closed_cache_only',
        refresh_policy: 'cache_only',
      });
    }
    if (url.includes('/api/ledger/entries')) {
      return jsonResponse(includeLedger ? [ledgerEntry] : []);
    }
    if (url.includes('/api/market/data-health')) {
      return jsonResponse({
        market_open: false,
        refresh_policy: 'cache_only',
        quotes: [
          {
            symbol: '600519',
            asset_class: 'stock',
            timestamp: '2026-04-21T14:30:00+08:00',
            price: 1600,
            quote_status: 'stale',
            quote_source: 'akshare',
            quote_age_seconds: 2_246_400,
            stale_reason: 'market_closed_cache_only',
            last_refresh_attempt: null,
            last_refresh_error: null,
            ...healthQuoteOverride,
          },
        ],
        provider_status: 'stale',
        provider_name: 'akshare',
        provider_configured: true,
        provider_requires_token: false,
        provider_supports_funds: true,
        provider_last_error: null,
        provider_timeout_seconds: 8,
        next_action: 'refresh_quotes_or_check_source',
        metadata_configured_count: 1,
        source_health: 'stale',
        cache_age_seconds: 2_246_400,
        latest_quote_timestamp: '2026-04-21T14:30:00+08:00',
        last_refresh_attempt: null,
        last_refresh_error: null,
        stale_symbols_count: includePosition ? 1 : 0,
        stale_symbols_sample: includePosition ? ['600519'] : [],
        ...marketHealthOverride,
      });
    }
    if (url.includes('/api/market/kline/600519')) {
      return jsonResponse([
        {
          timestamp: '2026-04-19T15:00:00+08:00',
          open: 1510,
          high: 1620,
          low: 1500,
          close: 1600,
          volume: 120000,
        },
        {
          timestamp: '2026-04-20T15:00:00+08:00',
          open: 1600,
          high: 1660,
          low: 1580,
          close: 1640,
          volume: 130000,
        },
      ]);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderHoldingDetail(
  options?: Parameters<typeof installHoldingFetchMock>[0],
) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  installHoldingFetchMock(options);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <HoldingDetailPage symbol="600519" />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders holding detail with cached quote status and ledger trace', async () => {
  const { container } = renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(await screen.findByText('Cached quote')).toBeTruthy();
  expect(
    await screen.findByText(
      'Cached quotes · valuation uses cached market data',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('Security buy')).toBeTruthy();
  expect(await screen.findByText('Consumes cash')).toBeTruthy();
  expect(screen.queryByText('trade_buy')).toBeNull();
  expect(await screen.findByText('initial allocation')).toBeTruthy();
  expect(await screen.findByText('-CN¥90,035.10')).toBeTruthy();
  expect(await screen.findByText('Gross amount CN¥90,000.00')).toBeTruthy();
  expect(screen.queryByText('Net cash impact -CN¥90,035.10')).toBeNull();
  expect(await screen.findByText('Commission CN¥30.00')).toBeTruthy();
  expect(await screen.findByText('Stamp tax CN¥0.00')).toBeTruthy();
  expect(await screen.findByText('Transfer fee CN¥5.10')).toBeTruthy();
  expect(screen.queryByText('Cost basis Moving average buy cost')).toBeNull();
  expect(await screen.findByText('akshare')).toBeTruthy();
  expect(await screen.findByText('26d')).toBeTruthy();
  expect(await screen.findByText('6.67%')).toBeTruthy();
  expect(await screen.findByText('Today PnL')).toBeTruthy();
  expect(await screen.findByText('CN¥240.00')).toBeTruthy();
  expect(await screen.findByText('0.25%')).toBeTruthy();
  expect(await screen.findByText('1,596.0000')).toBeTruthy();
  expect(await screen.findByText('Reported previous close')).toBeTruthy();
  expect((await screen.findAllByText('1,500.0000')).length).toBeGreaterThan(0);
  expect((await screen.findAllByText('1,600.0000')).length).toBeGreaterThan(0);
  expect(await screen.findByText('Price range / K-line')).toBeTruthy();
  expect(await screen.findByText('CN¥1,640.00')).toBeTruthy();
  expect(screen.queryByText('6.7%')).toBeNull();
  expect(
    await screen.findByText('Market closed; using cached quote'),
  ).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/real-time|latest price|NaN/i);

  const ledgerScroll = await screen.findByTestId('holding-ledger-scroll');
  const ledgerTable = container.querySelector(
    '[data-testid="holding-ledger-table"]',
  );
  expect(ledgerScroll.className).toContain('overflow-x-scroll');
  expect(ledgerScroll.className).toContain('pb-2');
  expect(ledgerTable?.className).toContain('w-[880px]');
  expect(ledgerTable?.className).toContain('min-w-max');
});

test('explains local average cost and broker displayed cost basis when evidence exists', async () => {
  renderHoldingDetail({
    positionOverride: {
      broker_displayed_unit_cost: 1502.3456,
      broker_displayed_cost_basis: 90140.736,
      broker_cost_basis_difference: 140.736,
      broker_cost_basis_method: 'broker_remaining_cost',
      broker_cost_basis_status: 'available',
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(await screen.findByText('Local moving average cost')).toBeTruthy();
  expect(await screen.findByText('Broker displayed cost')).toBeTruthy();
  expect(await screen.findByText('Cost basis difference')).toBeTruthy();
  expect(
    await screen.findByText('Broker remaining-position cost'),
  ).toBeTruthy();
  expect((await screen.findAllByText('1,500.0000')).length).toBeGreaterThan(0);
  expect(await screen.findByText('1,502.3456')).toBeTruthy();
  expect(await screen.findByText('CN¥140.74')).toBeTruthy();
  expect(await screen.findByText('Cost basis review needed')).toBeTruthy();
  expect(
    await screen.findByText(
      'Broker displayed cost differs from Karkinos local moving average cost. Review Account Truth evidence before relying on cost-basis P/L.',
    ),
  ).toBeTruthy();
});

test('shows ledger-projected remaining cost without presenting it as broker-confirmed evidence', async () => {
  renderHoldingDetail({
    positionOverride: {
      broker_displayed_unit_cost: 9.0261,
      broker_displayed_cost_basis: 1805.22,
      broker_cost_basis_difference: -196.78,
      broker_cost_basis_method: 'broker_remaining_cost',
      broker_cost_basis_status: 'projected_from_ledger',
      quantity: 200,
      avg_cost: 10.01,
      market_value: 2500,
      unrealized_pnl: 498,
    },
    liveItemOverride: {
      quantity: 200,
      avg_cost: 10.01,
      market_value: 2500,
      since_buy_pnl: 498,
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(
    await screen.findByText('Ledger-projected remaining cost'),
  ).toBeTruthy();
  expect(await screen.findByText('Projected from local ledger')).toBeTruthy();
  expect(await screen.findByText('CN¥1,805.22')).toBeTruthy();
  expect(await screen.findByText('9.0261')).toBeTruthy();
  expect(await screen.findByText('-CN¥196.78')).toBeTruthy();
  expect(screen.queryByText('Broker displayed cost')).toBeNull();
  expect(screen.queryByText('Cost basis review needed')).toBeNull();
  expect(
    screen.queryByText(
      'Broker displayed cost differs from Karkinos local moving average cost. Review Account Truth evidence before relying on cost-basis P/L.',
    ),
  ).toBeNull();
});

test('keeps holding summary and kline regions responsive on narrow screens', async () => {
  const { container } = renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const summaryHeader = screen.getByTestId('holding-summary-header');
  const summaryTitle = screen.getByTestId('holding-summary-title');
  const summarySymbol = screen.getByTestId('holding-summary-symbol');
  const summaryGrid = screen.getByTestId('holding-summary-metrics');
  const metricCards = container.querySelectorAll(
    '[data-testid="holding-summary-metric"]',
  );
  const chartPanel = screen.getByTestId('holding-kline-panel');
  const chartScroll = screen.getByTestId('price-structure-chart-scroll');
  const chartCanvas = screen.getByTestId('price-structure-chart-canvas');

  expect(summaryHeader.className).toContain('min-w-0');
  expect(summaryTitle.className).toContain('break-words');
  expect(summarySymbol.className).toContain('shrink-0');
  expect(summaryGrid.className).toContain('grid-cols-1');
  expect(summaryGrid.className).toContain('min-w-0');
  expect(metricCards.length).toBeGreaterThan(0);
  for (const card of metricCards) {
    expect(card.className).toContain('min-w-0');
  }
  expect(chartPanel.className).toContain('overflow-hidden');
  expect(chartScroll.className).toContain('overflow-x-auto');
  expect(chartCanvas.className).toContain('min-w-[640px]');
});

test('keeps the holding detail header compact and non-duplicative', async () => {
  const { container } = renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const header = container.querySelector(
    '[data-testid="holding-detail-header"]',
  );
  expect(header).not.toBeNull();
  expect(header?.querySelectorAll('a[href="/portfolio"]').length).toBe(1);
  expect(header?.textContent).toContain('Holding detail');
  expect(header?.textContent).toContain('Cached quote');
  expect(header?.textContent).not.toContain('Quote & data status');
  expect(
    header?.querySelector('[data-testid="holding-header-status-card"]'),
  ).toBeNull();
});

test('keeps quote status and action panels readable with long runtime values', async () => {
  const { container } = renderHoldingDetail({
    positionOverride: {
      quote_timestamp: '2026-06-16T11:04:56.000000+08:00',
      quote_source: longProviderName,
      stale_reason: longStaleReason,
      refresh_policy: 'cache_only_after_market_data_permission_fallback',
    },
    liveItemOverride: {
      quote_timestamp: '2026-06-16T11:04:56.000000+08:00',
      quote_source: longProviderName,
      stale_reason: longStaleReason,
      refresh_policy: 'cache_only_after_market_data_permission_fallback',
    },
    healthQuoteOverride: {
      timestamp: '2026-06-16T11:04:56.000000+08:00',
      quote_source: longProviderName,
      stale_reason: longStaleReason,
    },
    marketHealthOverride: {
      provider_name: longProviderName,
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const quotePanel = screen.getByTestId('holding-quote-status-panel');
  const riskPanel = screen.getByTestId('holding-risk-exposure-panel');
  const actionsPanel = screen.getByTestId('holding-related-actions-panel');
  const infoRows = container.querySelectorAll(
    '[data-testid="holding-info-row"]',
  );
  const values = container.querySelectorAll(
    '[data-testid="holding-info-row-value"]',
  );
  const actionLinks = container.querySelectorAll(
    '[data-testid="holding-related-action-link"]',
  );

  expect(quotePanel.className).toContain('min-w-0');
  expect(riskPanel.className).toContain('min-w-0');
  expect(actionsPanel.className).toContain('min-w-0');
  expect(infoRows.length).toBeGreaterThan(0);
  for (const row of infoRows) {
    expect(row.className).toContain('grid');
    expect(row.className).toContain('min-w-0');
  }
  for (const value of values) {
    expect(value.className).toContain('break-words');
    expect(value.className).toContain('min-w-0');
  }
  for (const link of actionLinks) {
    expect(link.className).toContain('break-words');
  }
});

test('shows not found state when the symbol is absent', async () => {
  renderHoldingDetail({ includePosition: false });

  expect(await screen.findByText('Holding not found')).toBeTruthy();
  expect(
    await screen.findByText(
      'This symbol is not present in the current portfolio snapshot.',
    ),
  ).toBeTruthy();
});

test('shows ledger empty state without breaking the page', async () => {
  renderHoldingDetail({ includeLedger: false });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(
    await screen.findByText(
      'No ledger trace is available for this symbol yet.',
    ),
  ).toBeTruthy();
});

test('shows core error state when portfolio detail cannot load', async () => {
  renderHoldingDetail({ failCore: true });

  expect(
    await screen.findByText('Failed to load holding detail.'),
  ).toBeTruthy();
});
