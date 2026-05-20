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
  market_value: 96000,
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
}: {
  includePosition?: boolean;
  includeLedger?: boolean;
  failCore?: boolean;
} = {}) {
  const positions = includePosition ? [position] : [];
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
                    today_change: 0,
                    today_change_pct: null,
                    baseline_price: null,
                    baseline_timestamp: null,
                    baseline_source: 'unavailable',
                    quote_status: 'stale',
                    quote_source: 'akshare',
                    quote_age_seconds: 2_246_400,
                    stale_reason: 'market_closed_cache_only',
                    refresh_policy: 'cache_only',
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
      });
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

  render(
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
  renderHoldingDetail();

  expect(await screen.findByText('600519 Position')).toBeTruthy();
  expect(await screen.findByText('Kweichow Moutai')).toBeTruthy();
  expect(await screen.findByText('Cached quote')).toBeTruthy();
  expect(
    await screen.findByText(
      'Cached quotes · valuation uses cached market data',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('trade_buy')).toBeTruthy();
  expect(await screen.findByText('initial allocation')).toBeTruthy();
  expect(await screen.findByText('akshare')).toBeTruthy();
  expect(await screen.findByText('26d')).toBeTruthy();
  expect(await screen.findByText('market_closed_cache_only')).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/real-time|latest price|NaN/i);
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

  expect(await screen.findByText('600519 Position')).toBeTruthy();
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
