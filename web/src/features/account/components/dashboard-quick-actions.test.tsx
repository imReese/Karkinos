import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { DashboardQuickActions } from './dashboard-quick-actions';

function renderWithProviders(ui: ReactElement) {
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

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>{ui}</PreferencesProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('surfaces cached quote status and homepage action paths', () => {
  renderWithProviders(
    <DashboardQuickActions
      overview={{
        total_equity: 4260.88,
        available_cash: 0,
        total_deposits: 4000,
        positions_count: 3,
        unrealized_pnl: 260.88,
        realized_pnl: 0,
        cash_ratio: 0,
        valuation_timestamp: '2026-05-18T00:18:00+08:00',
        quote_status: 'stale',
        quote_age_seconds: 900,
        stale_reason: 'quote_older_than_expected_session',
        refresh_policy: 'cache_only',
      }}
      marketHealth={{
        quotes: [],
        market_open: false,
        refresh_policy: 'cache_only',
        provider_status: 'degraded',
        provider_name: 'akshare',
        provider_configured: true,
        provider_requires_token: false,
        provider_supports_funds: true,
        provider_last_error: null,
        provider_timeout_seconds: 8,
        next_action: 'refresh_quotes_or_check_source',
        metadata_configured_count: 1,
        source_health: 'stale',
        cache_age_seconds: 900,
        latest_quote_timestamp: '2026-05-18T00:18:00+08:00',
        last_refresh_attempt: null,
        last_refresh_error: null,
        stale_symbols_count: 3,
        stale_symbols_sample: ['019999'],
      }}
      symbols={['019999']}
    />,
  );

  expect(screen.getByText('Cached quotes')).toBeTruthy();
  expect(
    screen.getByText(/Quote older than expected trading session/),
  ).toBeTruthy();
  expect(
    screen.getByText('Refresh quotes or check the data source'),
  ).toBeTruthy();
  expect(screen.queryByText('quote_older_than_expected_session')).toBeNull();
  expect(
    screen.getByRole('link', { name: 'Add ledger entry' }).getAttribute('href'),
  ).toBe('/activity');
  expect(
    screen.getByRole('link', { name: 'Trading desk' }).getAttribute('href'),
  ).toBe('/trading');
});

test('treats cache source health as cached quotes on the homepage', () => {
  renderWithProviders(
    <DashboardQuickActions
      overview={{
        total_equity: 4260.88,
        available_cash: 0,
        total_deposits: 4000,
        positions_count: 3,
        unrealized_pnl: 260.88,
        realized_pnl: 0,
        cash_ratio: 0,
        valuation_timestamp: '2026-05-18T10:18:00+08:00',
        quote_status: 'live',
        quote_age_seconds: 120,
        refresh_policy: 'live',
      }}
      marketHealth={{
        quotes: [],
        market_open: true,
        refresh_policy: 'live',
        provider_status: 'cache',
        provider_name: 'akshare',
        provider_configured: true,
        provider_requires_token: false,
        provider_supports_funds: true,
        provider_last_error: null,
        provider_timeout_seconds: 8,
        next_action: 'refresh_quotes_or_check_source',
        metadata_configured_count: 1,
        source_health: 'cache',
        cache_age_seconds: 120,
        latest_quote_timestamp: '2026-05-18T10:18:00+08:00',
        last_refresh_attempt: null,
        last_refresh_error: null,
        stale_symbols_count: 1,
        stale_symbols_sample: ['600519'],
        has_persistent_cache: true,
        persistent_cache_status: 'available',
      }}
      symbols={['600519']}
    />,
  );

  expect(screen.getByText('Cached quotes')).toBeTruthy();
  expect(screen.queryByText('Valuation available')).toBeNull();
  expect(
    screen.getByText('Refresh quotes or check the data source'),
  ).toBeTruthy();
});

test('lists concrete holdings when fund NAV is still estimate-only', () => {
  renderWithProviders(
    <DashboardQuickActions
      overview={{
        total_equity: 4260.88,
        available_cash: 0,
        total_deposits: 4000,
        positions_count: 1,
        unrealized_pnl: 260.88,
        realized_pnl: 0,
        cash_ratio: 0,
        valuation_timestamp: '2026-06-17T22:21:00+08:00',
        quote_status: 'stale',
        stale_reason: 'confirmed_fund_nav_missing_estimate_only',
        refresh_policy: 'cache_only',
      }}
      quoteDiagnostics={[
        {
          symbol: '019999',
          name: 'Everwin Advanced Manufacturing Fund C',
          asset_class: 'fund',
          quote_status: 'stale',
          quote_source: 'eastmoney_fund_estimate',
          stale_reason: 'confirmed_fund_nav_missing_estimate_only',
          quote_timestamp: '2026-06-17 15:00',
        },
      ]}
      symbols={['019999']}
    />,
  );

  expect(screen.getByText('Affected holdings')).toBeTruthy();
  expect(
    screen.getByText('Everwin Advanced Manufacturing Fund C'),
  ).toBeTruthy();
  expect(screen.getByText('019999 · Fund')).toBeTruthy();
  expect(screen.getByText('Using estimate')).toBeTruthy();
  expect(
    screen.getAllByText('Wait for confirmed fund NAV or sync NAV data').length,
  ).toBeGreaterThan(0);
});

test('refresh action calls the market refresh endpoint with dashboard symbols', async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      requested_symbols: ['019999'],
      refreshed: [],
      failed: [],
      skipped: [
        {
          symbol: '019999',
          status: 'stale',
          quote_timestamp: null,
          quote_source: null,
          quote_age_seconds: null,
          error: null,
          reason: 'provider_timeout',
          last_refresh_attempt: '2026-05-18T00:18:00+08:00',
          last_refresh_error: 'provider_timeout',
        },
      ],
      refresh_policy: 'cache_only',
      market_open: false,
      started_at: '2026-05-18T00:18:00+08:00',
      completed_at: '2026-05-18T00:18:01+08:00',
      duration_ms: 1000,
      quote_status: 'stale',
      last_refresh_attempt: '2026-05-18T00:18:00+08:00',
      last_refresh_error: 'provider_timeout',
      message: 'Quote source returned cached quotes',
    }),
  });
  vi.stubGlobal('fetch', fetchMock);

  renderWithProviders(
    <DashboardQuickActions
      overview={{
        total_equity: 4260.88,
        available_cash: 0,
        total_deposits: 4000,
        positions_count: 1,
        unrealized_pnl: 260.88,
        realized_pnl: 0,
        cash_ratio: 0,
        quote_status: 'stale',
      }}
      symbols={['019999']}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Refresh quotes' }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(fetchMock.mock.calls[0][0]).toBe('/api/market/quotes/refresh');
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    symbols: ['019999'],
    force: true,
  });
});

test('points provider timeouts to data source settings', () => {
  renderWithProviders(
    <DashboardQuickActions
      overview={{
        total_equity: 4260.88,
        available_cash: 0,
        total_deposits: 4000,
        positions_count: 1,
        unrealized_pnl: 260.88,
        realized_pnl: 0,
        cash_ratio: 0,
        quote_status: 'stale',
      }}
      marketHealth={{
        quotes: [],
        market_open: true,
        refresh_policy: 'live',
        provider_status: 'degraded',
        provider_name: 'akshare',
        provider_configured: true,
        provider_requires_token: false,
        provider_supports_funds: false,
        provider_last_error: 'provider_timeout',
        provider_timeout_seconds: 8,
        next_action: 'use_cached_data',
        metadata_configured_count: 1,
        source_health: 'degraded',
        cache_age_seconds: 5,
        latest_quote_timestamp: '2026-05-18T00:18:00+08:00',
        last_refresh_attempt: '2026-05-18T00:18:00+08:00',
        last_refresh_error: 'provider_timeout',
        stale_symbols_count: 1,
        stale_symbols_sample: ['019999'],
        has_persistent_cache: true,
        latest_persistent_quote_timestamp: '2026-05-18T00:18:00+08:00',
        persistent_cache_status: 'available',
      }}
      symbols={['019999']}
    />,
  );

  expect(
    screen.getByText('Continue with local cached market data'),
  ).toBeTruthy();
  expect(
    screen.getByRole('link', { name: 'Data settings' }).getAttribute('href'),
  ).toBe('/settings');
});
