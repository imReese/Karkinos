import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
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
  fee_rule_version: 'broker_fee_schedule',
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
  closedPosition,
  ledgerEntriesOverride,
  accountStrategy = {
    strategy_id: 'dual_ma',
    strategy_name: 'dual_ma',
    status: 'research_only',
    scope: 'account',
    asset_class: null,
    symbol: null,
    effective_from: null,
    auto_trade_enabled: false,
    attribution_status: 'assignment_only',
    attributed_pnl: null,
    realized_pnl: null,
    unrealized_pnl: null,
    total_fees: null,
    notes: '',
    updated_at: '2026-06-18T10:00:00+08:00',
    limitations: [
      'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    ],
  },
  accountStrategyAttribution = {
    strategy_id: 'dual_ma',
    attribution_status: 'assignment_only',
    signal_count: 0,
    action_count: 0,
    risk_decision_count: 0,
    order_count: 0,
    fill_count: 0,
    unattributed_fill_count: 0,
    total_fees: 0,
    attributed_pnl: null,
    realized_pnl: null,
    unrealized_pnl: null,
    evidence_refs: [],
    limitations: [
      'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    ],
  },
  accountStrategyContribution = {
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
      'Contribution is estimated only from fully linked strategy fills and latest local quotes; manual, cash-flow, and missing-evidence movements are separated and excluded from net contribution.',
    ],
  },
  holdingStrategyAttribution = {
    strategy_id: 'dual_ma',
    symbol: '600519',
    assignment_scope: 'account',
    assignment_applies_to_symbol: true,
    attribution_status: 'not_started',
    signal_count: 0,
    action_count: 0,
    risk_decision_count: 0,
    order_count: 0,
    fill_count: 0,
    evidence_refs: [],
    limitations: [
      'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    ],
  },
}: {
  includePosition?: boolean;
  includeLedger?: boolean;
  failCore?: boolean;
  positionOverride?: Partial<typeof position> & Record<string, unknown>;
  liveItemOverride?: Record<string, unknown>;
  healthQuoteOverride?: Record<string, unknown>;
  marketHealthOverride?: Record<string, unknown>;
  closedPosition?: Record<string, unknown>;
  ledgerEntriesOverride?: Array<Record<string, unknown>>;
  accountStrategy?: Record<string, unknown>;
  accountStrategyAttribution?: Record<string, unknown>;
  accountStrategyContribution?: Record<string, unknown>;
  holdingStrategyAttribution?: Record<string, unknown> | null;
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
        valuation_snapshot_id: 'valuation-1',
        ledger_cutoff_id: 21,
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
            closed_positions: closedPosition ? [closedPosition] : [],
            position_review_items: [],
            valuation_snapshot_id: 'valuation-1',
            ledger_cutoff_id: 21,
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
        valuation_snapshot_id: 'valuation-1',
        ledger_cutoff_id: 21,
      });
    }
    if (url.includes('/api/ledger/entries')) {
      return jsonResponse(
        ledgerEntriesOverride ?? (includeLedger ? [ledgerEntry] : []),
      );
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
    if (url.includes('/api/market/kline/')) {
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
    if (url.includes('/api/account-strategy/holdings/')) {
      return jsonResponse(
        url.includes('/holdings/600519/') ? holdingStrategyAttribution : null,
      );
    }
    if (url.includes('/api/account-strategy/attribution')) {
      return jsonResponse(accountStrategyAttribution);
    }
    if (url.includes('/api/account-strategy/contribution')) {
      return jsonResponse(accountStrategyContribution);
    }
    if (url.includes('/api/account-strategy')) {
      return jsonResponse(accountStrategy);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderHoldingDetail(
  options?: Parameters<typeof installHoldingFetchMock>[0],
  symbol = '600519',
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
        <HoldingDetailPage symbol={symbol} />
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
  expect(await screen.findByText('-¥90,035.10')).toBeTruthy();
  expect(await screen.findByText('Gross amount ¥90,000.00')).toBeTruthy();
  expect(await screen.findByText('Net cash impact -¥90,035.10')).toBeTruthy();
  expect(await screen.findByText('Commission ¥30.00')).toBeTruthy();
  expect(await screen.findByText('Stamp tax ¥0.00')).toBeTruthy();
  expect(await screen.findByText('Transfer fee ¥5.10')).toBeTruthy();
  expect(screen.queryByText('Cost basis Moving average buy cost')).toBeNull();
  expect(await screen.findByText('akshare')).toBeTruthy();
  expect(await screen.findByText('26d')).toBeTruthy();
  expect(await screen.findByText('6.67%')).toBeTruthy();
  expect(await screen.findByText('Today PnL')).toBeTruthy();
  expect(await screen.findByText('¥240.00')).toBeTruthy();
  expect(await screen.findByText('0.25%')).toBeTruthy();
  expect(await screen.findByText('1,596.0000')).toBeTruthy();
  expect(await screen.findByText('Reported previous close')).toBeTruthy();
  expect((await screen.findAllByText('1,500.0000')).length).toBeGreaterThan(0);
  expect((await screen.findAllByText('1,600.0000')).length).toBeGreaterThan(0);
  expect(await screen.findByText('Price range / K-line')).toBeTruthy();
  expect(await screen.findByText('¥1,640.00')).toBeTruthy();
  expect(await screen.findByText('Holding results & evidence')).toBeTruthy();
  expect(await screen.findByText('valuation-1')).toBeTruthy();
  expect(await screen.findByText('Persisted account ledger only')).toBeTruthy();
  expect(await screen.findByTestId('kline-trade-marker-buy')).toBeTruthy();
  expect((await screen.findAllByTestId('kline-reference-line')).length).toBe(1);
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

test('keeps a closed asset available as historical evidence without current exposure', async () => {
  const closedPosition = {
    symbol: '600066',
    name: 'Yutong Bus',
    display_name: 'Yutong Bus',
    asset_class: 'stock',
    quantity: 0,
    available_qty: 0,
    frozen_qty: 0,
    avg_cost: 0,
    latest_price: 28.75,
    market_value: 0,
    unrealized_pnl: 0,
    realized_pnl: 384.05,
    commission_paid: 17.95,
    today_change: 0,
    today_change_pct: null,
    baseline_price: 28.4,
    baseline_timestamp: '2026-04-19',
    baseline_source: 'market_bar_close',
    quote_timestamp: '2026-04-20T15:00:00+08:00',
    quote_status: 'live',
    quote_source: 'market_bar_close',
    quote_age_seconds: 0,
    stale_reason: null,
    refresh_policy: 'cache_only',
  };
  const closedLedgerEntries = [
    {
      ...ledgerEntry,
      id: 21,
      symbol: '600066',
      timestamp: '2026-04-20T15:00:00+08:00',
      entry_type: 'trade_sell',
      direction: 'sell',
      quantity: 100,
      price: 28.75,
      amount: 2870,
      gross_amount: 2875,
      net_cash_impact: 2870,
      note: 'second closing sale',
    },
    {
      ...ledgerEntry,
      id: 20,
      symbol: '600066',
      timestamp: '2026-04-20T15:00:00+08:00',
      entry_type: 'trade_sell',
      direction: 'sell',
      quantity: 100,
      price: 28.75,
      amount: 2870,
      gross_amount: 2875,
      net_cash_impact: 2870,
      note: 'first closing sale',
    },
    {
      ...ledgerEntry,
      id: 19,
      symbol: '600066',
      timestamp: '2026-04-19T15:00:00+08:00',
      quantity: 200,
      price: 26.7,
      amount: 5340,
      gross_amount: 5340,
      net_cash_impact: -5345,
      note: 'opening buy',
    },
  ];

  renderHoldingDetail(
    {
      includePosition: false,
      closedPosition,
      ledgerEntriesOverride: closedLedgerEntries,
    },
    '600066',
  );

  expect(await screen.findByText('Yutong Bus')).toBeTruthy();
  expect(await screen.findByText('Closed · history only')).toBeTruthy();
  expect(
    await screen.findByText(
      'This asset is closed and has no current portfolio exposure. Historical trades, fees, and realized PnL remain available for review.',
    ),
  ).toBeTruthy();
  expect((await screen.findAllByText('Security sell')).length).toBe(2);
  expect(await screen.findByText('Security buy')).toBeTruthy();
  expect((await screen.findAllByText('¥384.05')).length).toBeGreaterThan(0);
  expect((await screen.findAllByTestId('kline-trade-marker-sell')).length).toBe(
    2,
  );
  expect(
    screen.queryByTestId('holding-strategy-attribution-boundary'),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: /Refresh this quote/i }),
  ).toBeNull();
  expect(
    screen.queryByRole('link', { name: 'Open Trading approvals' }),
  ).toBeNull();
  expect(
    screen
      .getByRole('link', { name: 'View historical activity' })
      .getAttribute('href'),
  ).toBe('/activity?symbol=600066');
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
    await screen.findByText('Broker displayed remaining cost'),
  ).toBeTruthy();
  expect((await screen.findAllByText('1,500.0000')).length).toBeGreaterThan(0);
  expect(await screen.findByText('1,502.3456')).toBeTruthy();
  expect(await screen.findByText('¥140.74')).toBeTruthy();
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
  expect(await screen.findByText('¥1,805.22')).toBeTruthy();
  expect(await screen.findByText('9.0261')).toBeTruthy();
  expect(await screen.findByText('-¥196.78')).toBeTruthy();
  expect(screen.queryByText('Broker displayed cost')).toBeNull();
  expect(screen.queryByText('Cost basis review needed')).toBeNull();
  expect(
    screen.queryByText(
      'Broker displayed cost differs from Karkinos local moving average cost. Review Account Truth evidence before relying on cost-basis P/L.',
    ),
  ).toBeNull();
});

test('uses shared public fallback for unknown holding cost-basis methods', async () => {
  renderHoldingDetail({
    positionOverride: {
      broker_displayed_unit_cost: 1502.3456,
      broker_displayed_cost_basis: 90140.736,
      broker_cost_basis_difference: 140.736,
      broker_cost_basis_method: 'future_private_cost_basis_method',
      broker_cost_basis_status: 'available',
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(
    await screen.findByText('Cost basis method needs review'),
  ).toBeTruthy();
  expect(screen.queryByText(/future_private_cost_basis_method/)).toBeNull();
});

test('keeps holding summary and kline regions responsive on narrow screens', async () => {
  renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const summaryTitle = screen.getByTestId('holding-summary-title');
  const summaryGrid = screen.getByTestId('holding-summary-metrics');
  const metricStrip = summaryGrid.querySelector('dl');
  const metricCells = metricStrip?.querySelectorAll(':scope > div') ?? [];
  const chartPanel = screen.getByTestId('holding-kline-panel');
  const chartScroll = screen.getByTestId('price-structure-chart-scroll');
  const chartCanvas = screen.getByTestId('price-structure-chart-canvas');

  expect(summaryTitle.className).toContain('text-sm');
  expect(metricStrip?.className).toContain('min-w-0');
  expect(metricStrip?.className).toContain('sm:grid-cols-2');
  expect(metricStrip?.className).toContain('xl:grid-cols-4');
  expect(metricCells.length).toBeGreaterThan(0);
  for (const cell of metricCells) {
    expect(cell.className).toContain('min-w-0');
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
      quote_timestamp: '2026-01-15T11:04:56.000000+08:00',
      quote_source: longProviderName,
      stale_reason: longStaleReason,
      refresh_policy: 'cache_only_after_market_data_permission_fallback',
    },
    liveItemOverride: {
      quote_timestamp: '2026-01-15T11:04:56.000000+08:00',
      quote_source: longProviderName,
      stale_reason: longStaleReason,
      refresh_policy: 'cache_only_after_market_data_permission_fallback',
    },
    healthQuoteOverride: {
      timestamp: '2026-01-15T11:04:56.000000+08:00',
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

test('links the holding detail to a single-instrument strategy loop with symbol context', async () => {
  renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const link = screen.getByRole('link', {
    name: 'Run strategy research for this holding',
  });
  expect(link.getAttribute('href')).toBe(
    '/backtest?symbol=600519&assetClass=stock&source=portfolio',
  );
  expect(link.textContent).not.toContain('strategy_loop');
});

test('explains that holding PnL is not attributed to strategy without linked fills', async () => {
  renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = screen.getByTestId('holding-strategy-attribution-boundary');
  expect(card.textContent).toContain('Strategy attribution boundary');
  expect(card.textContent).toContain('No linked strategy fills yet');
  expect(card.textContent).toContain(
    'This holding does not yet have a complete strategy attribution evidence chain. Its P/L stays account-level until the missing signal, review, order, or fill reference is available.',
  );

  const researchLink = within(card).getByRole('link', {
    name: 'Review strategy research evidence',
  });
  expect(researchLink.getAttribute('href')).toBe(
    '/backtest?symbol=600519&assetClass=stock&source=portfolio',
  );
});

test('shows missing attribution prerequisites before linked fills exist', async () => {
  renderHoldingDetail();

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = screen.getByTestId('holding-strategy-attribution-boundary');
  expect(card.textContent).toContain('Attribution review readiness');
  expect(card.textContent).toContain('Evidence still incomplete');
  expect(card.textContent).toContain('Strategy signal missing');
  expect(card.textContent).toContain('Manual review missing');
  expect(card.textContent).toContain('Risk check missing');
  expect(card.textContent).toContain('Order evidence missing');
  expect(card.textContent).toContain('Fill evidence missing');
  expect(card.textContent).toContain(
    'Holding PnL is still not assigned to the strategy until review is complete.',
  );
});

test('shows linked symbol-level attribution evidence without claiming holding PnL', async () => {
  renderHoldingDetail({
    accountStrategy: {
      strategy_id: 'dual_ma',
      strategy_name: 'dual_ma',
      status: 'research_only',
      scope: 'symbol',
      asset_class: null,
      symbol: '600519',
      effective_from: '2026-06-18',
      auto_trade_enabled: false,
      attribution_status: 'evidence_linked_pnl_pending',
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      total_fees: null,
      notes: '',
      updated_at: '2026-06-18T10:00:00+08:00',
      limitations: [],
    },
    accountStrategyAttribution: {
      strategy_id: 'dual_ma',
      attribution_status: 'evidence_linked_pnl_pending',
      signal_count: 2,
      action_count: 2,
      risk_decision_count: 2,
      order_count: 2,
      fill_count: 2,
      unattributed_fill_count: 0,
      total_fees: 8.2,
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      evidence_refs: ['signal:1', 'order:ORD-1', 'fill:FILL-1'],
      limitations: [
        'P/L contribution is not calculated until fills are reconciled with position and valuation history.',
      ],
    },
    accountStrategyContribution: {
      strategy_id: 'dual_ma',
      contribution_status: 'estimated_from_linked_fills',
      strategy_health_status: 'healthy',
      strategy_health_reasons: ['linked_fill_evidence_available'],
      linked_fill_count: 2,
      gross_realized_pnl: 0,
      gross_unrealized_pnl: 32,
      total_commission: 7,
      total_slippage: 1,
      total_tax: 0.2,
      net_contribution: 23.8,
      unattributed_account_pnl: 4,
      manual_unattributed_pnl: 12,
      cash_flow_pnl: 3,
      missing_valuation_symbols: [],
      evidence_refs: ['fill:FILL-1', 'fill:FILL-2'],
      limitations: [
        'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
      ],
    },
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'symbol',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 2,
      action_count: 2,
      risk_decision_count: 2,
      order_count: 2,
      fill_count: 2,
      evidence_refs: ['signal:1', 'order:ORD-1', 'fill:FILL-1'],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Linked strategy evidence available');
  expect(card.textContent).toContain(
    'Strategy contribution remains review-only for this holding; manual trades and cash flows stay separate until attribution is reviewed.',
  );
  expect(card.textContent).toContain('Dual Moving Average');
  expect(card.textContent).toContain(
    'Holding evidence linked; review required',
  );
  expect(card.textContent).toContain('2 linked fills');
  expect(card.textContent).not.toContain('¥23.80');
});

test('uses holding-level attribution report for exact strategy evidence counts', async () => {
  renderHoldingDetail({
    accountStrategy: {
      strategy_id: 'dual_ma',
      strategy_name: 'dual_ma',
      status: 'research_only',
      scope: 'account',
      asset_class: null,
      symbol: null,
      effective_from: '2026-06-18',
      auto_trade_enabled: false,
      attribution_status: 'assignment_only',
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      total_fees: null,
      notes: '',
      updated_at: '2026-06-18T10:00:00+08:00',
      limitations: [],
    },
    accountStrategyAttribution: {
      strategy_id: 'dual_ma',
      attribution_status: 'evidence_linked_pnl_pending',
      signal_count: 8,
      action_count: 8,
      risk_decision_count: 8,
      order_count: 8,
      fill_count: 8,
      unattributed_fill_count: 0,
      total_fees: 32,
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      evidence_refs: [
        'signal:1',
        'signal:2',
        'order:ORD-OTHER',
        'fill:FILL-OTHER',
      ],
      limitations: [],
    },
    accountStrategyContribution: {
      strategy_id: 'dual_ma',
      contribution_status: 'estimated_from_linked_fills',
      strategy_health_status: 'healthy',
      strategy_health_reasons: ['linked_fill_evidence_available'],
      linked_fill_count: 8,
      gross_realized_pnl: 0,
      gross_unrealized_pnl: 32,
      total_commission: 7,
      total_slippage: 1,
      total_tax: 0.2,
      net_contribution: 23.8,
      unattributed_account_pnl: 4,
      manual_unattributed_pnl: 12,
      cash_flow_pnl: 3,
      missing_valuation_symbols: [],
      evidence_refs: ['fill:FILL-OTHER'],
      limitations: [],
    },
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'account',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 1,
      evidence_refs: ['signal:1', 'order:ORD-HOLDING-1', 'fill:FILL-HOLDING-1'],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Linked strategy evidence available');
  expect(card.textContent).toContain('1 linked fills');
  expect(card.textContent).toContain('3');
  expect(card.textContent).not.toContain('8 linked fills');
  expect(card.textContent).not.toContain('¥23.80');
});

test('shows holding attribution evidence refs as localized audit chain items', async () => {
  renderHoldingDetail({
    accountStrategy: {
      strategy_id: 'dual_ma',
      strategy_name: 'dual_ma',
      status: 'research_only',
      scope: 'account',
      asset_class: null,
      symbol: null,
      effective_from: '2026-06-18',
      auto_trade_enabled: false,
      attribution_status: 'assignment_only',
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      total_fees: null,
      notes: '',
      updated_at: '2026-06-18T10:00:00+08:00',
      limitations: [],
    },
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'account',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 1,
      evidence_refs: [
        'signal:1',
        'action:101',
        'risk:RISK-HOLDING-1',
        'review:1',
        'paper_shadow_order:paper-shadow-preview:dual_ma:600519:buy:100:29.17',
        'order:ORD-HOLDING-1',
        'fill:FILL-HOLDING-1',
      ],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Evidence chain');
  expect(card.textContent).toContain('Signal evidence');
  expect(card.textContent).toContain('Candidate action');
  expect(card.textContent).toContain('Risk check');
  expect(card.textContent).toContain('Manual review');
  expect(card.textContent).toContain('Simulation review order');
  expect(card.textContent).toContain('Audit ref 29.17');
  expect(card.textContent).toContain('Order evidence');
  expect(card.textContent).toContain('Fill evidence');
  expect(card.textContent).toContain('Audit ref 1');
  expect(card.textContent).toContain('Audit ref ORD-HOLDING-1');
  expect(card.textContent).toContain('Audit ref FILL-HOLDING-1');
  expect(card.textContent).not.toContain('signal:1');
  expect(card.textContent).not.toContain('paper_shadow_order');
  expect(card.textContent).not.toContain('paper-shadow-preview');
  expect(card.textContent).not.toContain('dual_ma');
  expect(card.textContent).not.toContain('order:ORD-HOLDING-1');
  expect(card.textContent).not.toContain('fill:FILL-HOLDING-1');
});

test('explains attribution review readiness before assigning holding PnL to strategy', async () => {
  renderHoldingDetail({
    accountStrategy: {
      strategy_id: 'dual_ma',
      strategy_name: 'dual_ma',
      status: 'research_only',
      scope: 'account',
      asset_class: null,
      symbol: null,
      effective_from: '2026-06-18',
      auto_trade_enabled: false,
      attribution_status: 'assignment_only',
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      total_fees: null,
      notes: '',
      updated_at: '2026-06-18T10:00:00+08:00',
      limitations: [],
    },
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'account',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 1,
      evidence_refs: [
        'signal:1',
        'action:101',
        'risk:RISK-HOLDING-1',
        'review:1',
        'order:ORD-HOLDING-1',
        'fill:FILL-HOLDING-1',
      ],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Attribution review readiness');
  expect(card.textContent).toContain('Ready for review');
  expect(card.textContent).toContain('Strategy signal linked');
  expect(card.textContent).toContain('Manual review linked');
  expect(card.textContent).toContain('Risk check linked');
  expect(card.textContent).toContain('Order evidence linked');
  expect(card.textContent).toContain('Fill evidence linked');
  expect(card.textContent).toContain(
    'Holding PnL is still not assigned to the strategy until review is complete.',
  );
  expect(card.textContent).not.toContain('¥23.80');
});

test('uses structured holding attribution prerequisites instead of parsing evidence refs', async () => {
  renderHoldingDetail({
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'account',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 1,
      evidence_refs: [
        'signal:1',
        'action:101',
        'risk:RISK-HOLDING-1',
        'order:ORD-HOLDING-1',
        'fill:FILL-HOLDING-1',
      ],
      review_prerequisites: [
        { key: 'strategy_signal', passed: true, evidence_count: 1 },
        { key: 'candidate_action', passed: true, evidence_count: 1 },
        { key: 'risk_gate', passed: true, evidence_count: 1 },
        { key: 'manual_review', passed: true, evidence_count: 1 },
        { key: 'order_evidence', passed: true, evidence_count: 1 },
        { key: 'fill_evidence', passed: true, evidence_count: 1 },
        { key: 'future_gate', passed: false, evidence_count: 0 },
      ],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Candidate action linked');
  expect(card.textContent).toContain('Manual review linked');
  expect(card.textContent).toContain('Evidence missing');
  expect(card.textContent).not.toContain('Manual review missing');
  expect(card.textContent).not.toContain('future_gate');
});

test('shows a localized next action for the first missing attribution prerequisite', async () => {
  renderHoldingDetail({
    holdingStrategyAttribution: {
      strategy_id: 'dual_ma',
      symbol: '600519',
      assignment_scope: 'account',
      assignment_applies_to_symbol: true,
      attribution_status: 'holding_evidence_linked_review_required',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 1,
      evidence_refs: [
        'signal:1',
        'action:101',
        'risk:RISK-HOLDING-1',
        'order:ORD-HOLDING-1',
        'fill:FILL-HOLDING-1',
      ],
      review_prerequisites: [
        { key: 'strategy_signal', passed: true, evidence_count: 1 },
        { key: 'candidate_action', passed: true, evidence_count: 1 },
        { key: 'risk_gate', passed: true, evidence_count: 1 },
        { key: 'manual_review', passed: false, evidence_count: 0 },
        { key: 'order_evidence', passed: true, evidence_count: 1 },
        { key: 'fill_evidence', passed: true, evidence_count: 1 },
      ],
      limitations: [
        'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
      ],
    },
  });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('Next review step');
  expect(card.textContent).toContain(
    'Review the strategy candidate in Decision before this holding can enter attribution review.',
  );
  const actionLink = within(card).getByRole('link', {
    name: 'Open Decision review',
  });
  expect(actionLink.getAttribute('href')).toBe('/decision');
  expect(card.textContent).not.toContain('manual_review');
});

test('shows a next action when holding-level attribution readiness is unavailable', async () => {
  renderHoldingDetail({ holdingStrategyAttribution: null });

  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();

  const card = await screen.findByTestId(
    'holding-strategy-attribution-boundary',
  );
  expect(card.textContent).toContain('No linked strategy fills yet');
  expect(card.textContent).toContain('Next review step');
  expect(card.textContent).toContain(
    'Run or refresh the single-instrument strategy loop for this holding, then review signal, risk, simulation, and attribution evidence together.',
  );
  const actionLink = within(card).getByRole('link', {
    name: 'Review strategy research evidence',
  });
  expect(actionLink.getAttribute('href')).toBe(
    '/backtest?symbol=600519&assetClass=stock&source=portfolio',
  );
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
