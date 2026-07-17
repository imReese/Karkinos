import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { MarketPage } from './router';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const health = {
  quotes: [
    {
      symbol: '600519',
      asset_class: 'stock',
      timestamp: '2026-06-17T14:10:00+08:00',
      price: 100,
      quote_status: 'live',
      quote_source: 'fixture',
      quote_age_seconds: 60,
      stale_reason: null,
      last_refresh_attempt: '2026-06-17T14:10:00+08:00',
      last_refresh_error: null,
    },
  ],
  market_open: true,
  refresh_policy: 'live',
  provider_status: 'available',
  provider_name: 'fixture',
  provider_configured: true,
  provider_requires_token: false,
  provider_supports_funds: true,
  provider_last_error: null,
  provider_timeout_seconds: 8,
  next_action: null,
  metadata_configured_count: 1,
  source_health: 'healthy',
  cache_age_seconds: 60,
  latest_quote_timestamp: '2026-06-17T14:10:00+08:00',
  last_refresh_attempt: '2026-06-17T14:10:00+08:00',
  last_refresh_error: null,
  stale_symbols_count: 0,
  stale_symbols_sample: [],
};

const currentHoldingMarketEvidenceReview = {
  schema_version: 'karkinos.current_holding_market_evidence_review.v1',
  status: 'complete',
  next_manual_action: 'none',
  current_holding_count: 1,
  confirmed_holding_count: 1,
  review_required_count: 0,
  fund_nav_review_count: 0,
  estimated_review_count: 0,
  stale_or_cached_review_count: 0,
  missing_or_error_review_count: 0,
  unknown_status_review_count: 0,
  refreshable_symbols: [],
  items: [],
  source_blockers: [],
  review_fingerprint: `sha256:${'b'.repeat(64)}`,
  valuation_snapshot_id: 'valuation-market-fixture',
  valuation_as_of: '2026-06-17T14:10:00+08:00',
  valuation_trade_date: '2026-06-17',
  valuation_policy: 'karkinos.persisted_valuation.v4',
  valuation_status: 'complete',
  ledger_cutoff_id: 27,
  ledger_fingerprint: 'ledger-market-fixture',
  quote_set_fingerprint: 'quotes-market-fixture',
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

function installMarketFetchMock(
  overrides: {
    health?: Record<string, unknown>;
    quotes?: Array<Record<string, unknown>>;
    marketEvidenceReview?: Record<string, unknown>;
  } = {},
) {
  const boardHealth = {
    ...health,
    ...overrides.health,
    quotes: overrides.quotes ?? health.quotes,
  };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/market/research-board')) {
        return jsonResponse({
          health: boardHealth,
          items: [
            {
              symbol: '600519',
              asset_class: 'stock',
              name: '测试标的',
              is_holding: true,
              quantity: 100,
              avg_cost: 90,
              market_value: 10000,
              unrealized_pnl: 1000,
              realized_pnl: 0,
              last_snapshot_at: '2026-06-17T14:10:00+08:00',
              price: 100,
              volume: 1000,
              research_count: 1,
              last_research_at: '2026-06-17T10:00:00+08:00',
            },
          ],
        });
      }
      if (url.includes('/api/portfolio/market-evidence-review')) {
        return jsonResponse(
          overrides.marketEvidenceReview ?? currentHoldingMarketEvidenceReview,
        );
      }
      if (url.includes('/api/market/fund-nav/confirmed/refresh')) {
        return jsonResponse({
          schema_version: 'karkinos.confirmed_fund_nav_refresh.v1',
          request_id: '12345678-1234-4234-8234-123456789abc',
          idempotent_replay: false,
          status: 'success',
          requested_symbols: ['FUND-A'],
          refreshed_symbols: ['FUND-A'],
          skipped_symbols: [],
          failed_symbols: {},
          run: {
            run_id: 'fund-nav-confirmed-fixture',
          },
          valuation_snapshot_id: 'valuation-market-fixture-next',
        });
      }
      if (url.includes('/api/market/quotes/refresh')) {
        return jsonResponse({
          quote_status: 'live',
          refreshed: [],
          skipped: [],
          failed: [],
        });
      }
      if (url.includes('/api/market/quote-fetch-runs')) {
        return jsonResponse([
          {
            run_id: 'run-1',
            trigger: 'manual',
            provider: 'fixture',
            asset_type: 'stock',
            status: 'completed',
            started_at: '2026-06-17T14:10:00+08:00',
            finished_at: '2026-06-17T14:10:01+08:00',
            symbol_count: 1,
            success_count: 1,
            failure_count: 0,
            cache_hit_count: 0,
            error_message: null,
            metadata: null,
          },
        ]);
      }
      if (url.includes('/api/market/research-notes')) {
        return jsonResponse({ items: [] });
      }
      if (url.includes('/api/market/instrument-metadata/backfill')) {
        return jsonResponse({
          provider: 'fixture',
          requested_count: 1,
          updated_count: 1,
          skipped_count: 0,
          failed_count: 0,
        });
      }
      if (url.includes('/api/market/bars/backfill')) {
        return jsonResponse({
          provider: 'fixture',
          interval: '1d',
          start: '2026-06-01',
          end: '2026-06-17',
          requested_count: 1,
          updated_count: 1,
          cached_count: 0,
          failed_count: 0,
        });
      }
      if (url.includes('/api/market/kline/')) {
        return jsonResponse([
          {
            timestamp: '2026-06-17T00:00:00+08:00',
            open: 98,
            high: 101,
            low: 97,
            close: 100,
            volume: 1000,
          },
        ]);
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderMarketPage(
  overrides: Parameters<typeof installMarketFetchMock>[0] = {},
) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installMarketFetchMock(overrides);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <MarketPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders market data operations and triggers manual backfills', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderMarketPage();

  expect(await screen.findByText('Data operations')).toBeTruthy();
  expect(await screen.findByText(/manual · completed/i)).toBeTruthy();

  await user.click(screen.getByRole('button', { name: 'Backfill metadata' }));
  await user.click(screen.getByRole('button', { name: 'Backfill daily bars' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/market/instrument-metadata/backfill',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/market/bars/backfill',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

test('counts cache estimated and missing quotes as market data needing confirmation', async () => {
  renderMarketPage({
    health: {
      source_health: 'cache',
      refresh_policy: 'cache_only',
      stale_symbols_count: undefined,
    },
    quotes: [
      { ...health.quotes[0], quote_status: 'cache' },
      { ...health.quotes[0], symbol: '000001', quote_status: 'estimated' },
      { ...health.quotes[0], symbol: '000002', quote_status: 'missing' },
    ],
  });

  expect((await screen.findAllByText('Cached quotes')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('Cache only')).length).toBeGreaterThan(0);
  expect(await screen.findByText('3 quotes need review')).toBeTruthy();
});

test('surfaces selected symbol next action without leaking raw data status codes', async () => {
  renderMarketPage({
    health: {
      source_health: 'cache',
      refresh_policy: 'cache_only',
      next_action: null,
    },
    quotes: [
      {
        ...health.quotes[0],
        quote_status: 'confirmed_nav_missing',
        quote_source: 'eastmoney_fund_estimate',
        stale_reason: 'confirmed_fund_nav_missing_estimate_only',
      },
    ],
  });

  expect(await screen.findByText('Confirmed NAV missing')).toBeTruthy();
  expect(
    await screen.findByText('Wait for confirmed fund NAV or sync NAV data'),
  ).toBeTruthy();
  expect(
    screen.queryByText('confirmed_fund_nav_missing_estimate_only'),
  ).toBeNull();
});

test('routes confirmed NAV blockers through confirmation-only ingestion', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderMarketPage({
    marketEvidenceReview: {
      ...currentHoldingMarketEvidenceReview,
      status: 'review_required',
      next_manual_action: 'review_current_holding_market_evidence',
      current_holding_count: 2,
      confirmed_holding_count: 1,
      review_required_count: 1,
      fund_nav_review_count: 1,
      refreshable_symbols: ['FUND-A'],
      items: [
        {
          symbol: 'FUND-A',
          name: '证据基金',
          asset_class: 'fund',
          quantity: 1200,
          quote_status: 'confirmed_nav_missing',
          quote_source: 'eastmoney_fund_estimate',
          quote_timestamp: '2026-06-17T14:10:00+08:00',
          stale_reason: 'confirmed_fund_nav_missing_estimate_only',
          nav_date: null,
          review_reason: 'confirmed_nav_missing',
          next_manual_action:
            'wait_for_confirmed_nav_then_run_explicit_refresh',
          explicit_refresh_eligible: true,
          blocks_authoritative_decisions: true,
        },
      ],
    },
  });

  const panel = await screen.findByTestId(
    'current-holding-market-evidence-review',
  );
  expect(within(panel).getByText('证据基金')).toBeTruthy();
  expect(within(panel).getByText(/FUND-A/)).toBeTruthy();
  expect(
    within(panel).getByText('1 current holding needs review'),
  ).toBeTruthy();
  expect(within(panel).getByTitle('valuation-market-fixture')).toBeTruthy();
  expect(
    within(panel).queryByRole('button', { name: 'Refresh quotes' }),
  ).toBeNull();

  await user.click(
    within(panel).getByRole('button', { name: 'Sync confirmed NAV' }),
  );

  await waitFor(() => {
    const refreshCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/api/market/fund-nav/confirmed/refresh'),
    );
    expect(refreshCall).toBeTruthy();
    const requestBody = JSON.parse(String(refreshCall?.[1]?.body));
    expect(requestBody.symbols).toEqual(['FUND-A']);
    expect(requestBody.request_id).toEqual(expect.any(String));
  });
  expect(
    await within(panel).findByText('1 confirmed fund NAV persisted'),
  ).toBeTruthy();
});
