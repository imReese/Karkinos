import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { MarketRefreshButton } from './market-refresh-button';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function createRefreshResponse(
  quoteStatus: 'live' | 'stale' | 'partial' | 'error' = 'live',
) {
  return {
    requested_symbols: ['600519'],
    refreshed:
      quoteStatus === 'live'
        ? [
            {
              symbol: '600519',
              status: 'refreshed',
              quote_timestamp: '2026-05-12T10:05:00+08:00',
              error: null,
              reason: null,
            },
          ]
        : [],
    failed:
      quoteStatus === 'error'
        ? [
            {
              symbol: '600519',
              status: 'failed',
              quote_timestamp: null,
              error: 'provider_timeout',
              reason: '行情源刷新超时，已保留缓存行情',
            },
          ]
        : [],
    skipped:
      quoteStatus === 'stale'
        ? [
            {
              symbol: '600519',
              status: 'stale',
              quote_timestamp: '2026-04-22T15:00:00',
              error: null,
              reason: '行情源没有返回新报价，当前仍基于缓存行情',
            },
          ]
        : [],
    refresh_policy: quoteStatus === 'stale' ? 'cache_only' : 'live',
    market_open: quoteStatus !== 'stale',
    started_at: '2026-05-12T10:05:00',
    completed_at: '2026-05-12T10:05:01',
    duration_ms: 1000,
    quote_status: quoteStatus,
    message:
      quoteStatus === 'stale'
        ? '行情源返回缓存行情'
        : quoteStatus === 'partial'
          ? '部分行情刷新完成'
          : quoteStatus === 'error'
            ? '行情刷新失败'
            : '行情刷新完成',
  };
}

function renderRefreshButton() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <MarketRefreshButton />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { invalidateSpy };
}

beforeEach(() => {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('calls refresh mutation when the button is clicked', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(jsonResponse(createRefreshResponse()));
  const user = userEvent.setup();
  renderRefreshButton();

  await user.click(screen.getByRole('button', { name: 'Refresh quotes' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/market/quotes/refresh',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: true }),
      }),
    );
  });
});

test('invalidates portfolio and market queries after refresh succeeds', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(createRefreshResponse()),
  );
  const user = userEvent.setup();
  const { invalidateSpy } = renderRefreshButton();

  await user.click(screen.getByRole('button', { name: 'Refresh quotes' }));

  await waitFor(() => {
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['market-data-health'],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['portfolio-live-holdings'],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['account-equity-curve-series'],
    });
  });
});

test('disables the button while refresh is pending', async () => {
  let resolveFetch: (response: Response) => void = () => undefined;
  vi.spyOn(globalThis, 'fetch').mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
  );
  const user = userEvent.setup();
  renderRefreshButton();

  const button = screen.getByRole('button', { name: 'Refresh quotes' });
  await user.click(button);

  expect(
    screen.getByRole('button', { name: 'Refreshing quotes' }),
  ).toHaveProperty('disabled', true);

  resolveFetch(jsonResponse(createRefreshResponse()));
  await screen.findByText('Quote refresh completed');
});

test('shows cached quote result without claiming real-time success', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(createRefreshResponse('stale')),
  );
  const user = userEvent.setup();
  renderRefreshButton();

  await user.click(screen.getByRole('button', { name: 'Refresh quotes' }));

  await screen.findByText('Quote source returned cached quotes');
  expect(screen.queryByText(/real-time/i)).toBeNull();
});

test('shows a clear failure state when refresh fails', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse({ detail: 'provider unavailable' }, { status: 503 }),
  );
  const user = userEvent.setup();
  renderRefreshButton();

  await user.click(screen.getByRole('button', { name: 'Refresh quotes' }));

  await screen.findByText(/Quote refresh failed/);
});
