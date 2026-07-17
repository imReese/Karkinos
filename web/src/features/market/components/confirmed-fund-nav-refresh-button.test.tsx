import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { ConfirmedFundNavRefreshButton } from './confirmed-fund-nav-refresh-button';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function createResponse(
  status: 'success' | 'failed',
  idempotentReplay = false,
) {
  return {
    schema_version: 'karkinos.confirmed_fund_nav_refresh.v1',
    request_id: '12345678-1234-4234-8234-123456789abc',
    idempotent_replay: idempotentReplay,
    status,
    next_manual_action:
      status === 'success'
        ? 'review_refreshed_current_holding_evidence'
        : 'wait_for_confirmed_nav_then_retry',
    requested_symbols: ['FUND-A'],
    refreshed_symbols: status === 'success' ? ['FUND-A'] : [],
    skipped_symbols: [],
    failed_symbols:
      status === 'failed' ? { 'FUND-A': 'confirmed NAV is not published' } : {},
    run: {
      run_id: `confirmed-nav-${status}-fixture`,
      trigger: 'fund_nav_sync',
      provider: 'deterministic_fixture',
      asset_type: 'fund',
      status,
      started_at: '2026-06-17T21:30:00+08:00',
      finished_at: '2026-06-17T21:30:01+08:00',
      symbol_count: 1,
      success_count: status === 'success' ? 1 : 0,
      failure_count: status === 'failed' ? 1 : 0,
      cache_hit_count: 0,
      error_message: null,
      metadata: { confirmation_only: true },
    },
    valuation_snapshot_id:
      status === 'success' ? 'valuation-confirmed-fixture' : null,
    provider_contact_performed: true,
    writes_market_data_only: true,
    does_not_mutate_oms: true,
    does_not_mutate_production_ledger: true,
    does_not_mutate_risk: true,
    does_not_mutate_kill_switch: true,
    does_not_change_capital_authority: true,
    authorizes_execution: false,
  };
}

function renderButton() {
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
        <ConfirmedFundNavRefreshButton symbols={['FUND-A']} />
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

test('posts only requested funds and records the visible audit run', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(jsonResponse(createResponse('success')));
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole('button', { name: 'Sync confirmed NAV' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/market/fund-nav/confirmed/refresh',
    );
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init).toEqual(expect.objectContaining({ method: 'POST' }));
    const body = JSON.parse(String(init?.body));
    expect(body.symbols).toEqual(['FUND-A']);
    expect(body.request_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
  expect(
    await screen.findByText('1 confirmed fund NAV persisted'),
  ).toBeTruthy();
  expect(screen.getByTitle('confirmed-nav-success-fixture')).toBeTruthy();
});

test('labels an idempotent replay without claiming another provider call', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(createResponse('success', true)),
  );
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole('button', { name: 'Sync confirmed NAV' }));

  expect(
    await screen.findByText(
      'Repeated request: reused the persisted audit run without contacting the data source again.',
    ),
  ).toBeTruthy();
});

test('keeps review explicit when same-day confirmed NAV is unavailable', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(createResponse('failed')),
  );
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole('button', { name: 'Sync confirmed NAV' }));

  expect(
    await screen.findByText(
      'No same-day confirmed NAV was published; the review items remain.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/persisted$/)).toBeNull();
});

test('invalidates evidence and decision projections after an audited run', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(createResponse('success')),
  );
  const user = userEvent.setup();
  const { invalidateSpy } = renderButton();

  await user.click(screen.getByRole('button', { name: 'Sync confirmed NAV' }));

  await waitFor(() => {
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['current-holding-market-evidence-review'],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['decision', 'trading-plan'],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['operations', 'today'],
    });
  });
});
