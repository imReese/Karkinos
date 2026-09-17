import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { AccountStateResponse } from '../overview-feature-boundary';
import { OverviewPage } from './overview-page';

function accountFixture(): AccountStateResponse {
  return {
    summary: {
      total_equity: 18585.11,
      available_cash: 6979.91,
      total_deposits: 20000,
      positions_count: 1,
      unrealized_pnl: -1400,
      realized_pnl: -14.89,
      cumulative_pnl: -1414.89,
      cumulative_return: null,
      today_pnl: -314.51,
      cash_ratio: 0.376,
      latest_session_date: '2026-09-11',
    },
    snapshot: {
      cash: 6979.91,
      total_equity: 18585.11,
      total_deposits: 20000,
      positions: [
        {
          symbol: 'fixture-fund',
          display_name: '合成基金',
          asset_class: 'fund',
          instrument_type: 'open_end_fund',
          quantity: 100,
          available_qty: 100,
          frozen_qty: 0,
          avg_cost: 10,
          market_value: 900,
          latest_price: 9,
          unrealized_pnl: -100,
          realized_pnl: 0,
          commission_paid: 0,
          quote_status: 'confirmed',
          pricing_kind: 'published_nav',
          pricing_as_of: '2026-09-11',
          pricing_authority: 'authoritative',
          nav_date: '2026-09-11',
          valuation_available: true,
        },
      ],
      allocation: [
        {
          symbol: 'fixture-fund',
          name: '合成基金',
          asset_class: 'fund',
          weight: 0.048,
          value: 900,
        },
      ],
      allocation_grouped: [],
      valuation_snapshot_id: 'synthetic-snapshot',
      valuation_status: 'complete',
      ledger_cutoff_id: 42,
      ledger_fingerprint: 'synthetic-ledger',
      quote_set_fingerprint: 'synthetic-quotes',
      valuation_policy: 'synthetic-policy',
    },
    risks: [],
    next_step: 'Continue observation',
    overview: {
      market_session: {
        status: 'non_trading_day',
        market_date: '2026-09-14',
        calendar_verified: true,
        latest_completed_trade_date: '2026-09-11',
        expected_quote_date: '2026-09-11',
        next_trading_date: '2026-09-14',
        blockers: [],
      },
      valuation_usability: 'usable',
      pricing_as_of: '2026-09-11',
      refresh_health: { status: 'healthy', latest_attempt: null, blockers: [] },
      decision_readiness: 'blocked',
      user_attention: [],
      attention_status: 'available',
    },
  };
}

const curve = [
  {
    timestamp: '2026-09-10T15:00:00+08:00',
    total: 18899.62,
    stocks: 0,
    funds: 11919.71,
    others: 0,
    cash: 6979.91,
  },
  {
    timestamp: '2026-09-11T15:00:00+08:00',
    total: 18585.11,
    stocks: 0,
    funds: 11605.2,
    others: 0,
    cash: 6979.91,
  },
];

function installFetch(state = accountFixture(), curveFailure = false) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/portfolio/state')) return Response.json(state);
    if (url.includes('/api/portfolio/equity-curve/series'))
      return curveFailure
        ? new Response('unavailable', { status: 503 })
        : Response.json(curve);
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function renderPage(locale: 'en' | 'zh' = 'en') {
  window.localStorage.setItem('karkinos.locale', locale);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const result = render(
    <PreferencesProvider>
      <QueryClientProvider client={client}>
        <OverviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { ...result, client };
}

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
    configurable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
    })),
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test('reads one coherent account projection and a separate canonical history', async () => {
  const fetch = installFetch();
  renderPage();
  await screen.findByTestId('overview-summary');
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
    '/api/portfolio/state',
    '/api/portfolio/equity-curve/series?range=1m',
  ]);
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  expect(screen.getByTestId('overview-cumulative-pnl')).toHaveTextContent(
    '-¥1,414.89',
  );
  expect(screen.getByTestId('overview-session-pnl')).toHaveTextContent(
    '-¥314.51',
  );
  expect(screen.getByText('Return unavailable')).toBeVisible();
  expect(screen.getByText(/37.6%/)).toBeVisible();
  expect(screen.queryByText('Current Drawdown')).not.toBeInTheDocument();
});

test('latest completed-session data on a verified non-trading day is usable with an empty attention queue', async () => {
  installFetch();
  renderPage();
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    'Data as of 09/11 · Market closed · Current valuation usable',
  );
  const queue = screen.getByTestId('overview-today-queue');
  expect(within(queue).getByText('0')).toBeVisible();
  expect(
    within(queue).getByText('No items need your attention today.'),
  ).toBeVisible();
  expect(within(queue).queryByRole('link')).not.toBeInTheDocument();
  expect(
    screen.queryByText(
      /Evidence complete|Evidence degraded|Cached quotes|Broker disabled/,
    ),
  ).not.toBeInTheDocument();
});

test('a later failed refresh does not contradict a usable published valuation', async () => {
  const state = accountFixture();
  state.overview.refresh_health = {
    status: 'degraded',
    latest_attempt: {
      status: 'failed',
      updated_at: '2026-09-12T09:00:00+08:00',
    },
    blockers: ['synthetic-provider-error'],
  };
  installFetch(state);
  renderPage();
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    'Current valuation usable',
  );
  expect(screen.getAllByRole('status')).toHaveLength(1);
  const details = screen.getByTestId('overview-data-details');
  expect(details).not.toHaveAttribute('open');
  expect(within(details).getByText('Latest refresh failed')).not.toBeVisible();
  await userEvent.click(within(details).getByText('Data details'));
  expect(within(details).getByText('Latest refresh failed')).toBeVisible();
  expect(within(details).getByText('synthetic-snapshot')).toBeVisible();
  expect(screen.getByTestId('overview-data-status')).not.toHaveTextContent(
    'review',
  );
});

test.each(['degraded', 'unavailable'] as const)(
  'renders canonical %s valuation without normalizing a closed market',
  async (status) => {
    const state = accountFixture();
    state.overview.valuation_usability = status;
    state.overview.pricing_as_of = '2026-09-10';
    installFetch(state);
    renderPage();
    const banner = await screen.findByTestId('overview-data-status');
    expect(banner).toHaveTextContent(
      status === 'degraded'
        ? 'Valuation evidence needs review'
        : 'Valuation unavailable',
    );
    expect(banner).not.toHaveTextContent('Current valuation usable');
  },
);

test('confirmed open-end fund NAV is instrument aware with no realtime or cache claim', async () => {
  const state = accountFixture();
  state.snapshot.positions[0].quote_status = 'cached';
  installFetch(state);
  renderPage();
  await screen.findByTestId('overview-summary');
  for (const label of screen.getAllByTestId('position-pricing-fixture-fund'))
    expect(label).toHaveTextContent('Published NAV · 09/11');
  expect(screen.queryByText('Live quote')).not.toBeInTheDocument();
  expect(screen.queryByText(/27h|Cached quote/)).not.toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /合成基金/ })[0]).toHaveAttribute(
    'href',
    '/portfolio/fixture-fund',
  );
});

test.each(['estimated_nav', 'nav_pending'] as const)(
  'keeps fund %s visibly non-authoritative',
  async (kind) => {
    const state = accountFixture();
    state.snapshot.positions[0].pricing_kind = kind;
    state.snapshot.positions[0].pricing_authority = 'non_authoritative';
    installFetch(state);
    renderPage();
    await screen.findByTestId('overview-summary');
    expect(
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent(
      kind === 'estimated_nav' ? 'Estimated NAV' : 'Confirmed NAV unavailable',
    );
    expect(
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent('Unconfirmed data');
  },
);

test('attention unavailable cannot masquerade as zero actions', async () => {
  const state = accountFixture();
  state.overview.attention_status = 'unavailable';
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('Attention status unavailable')).toBeVisible();
  expect(within(queue).queryByText('0')).not.toBeInTheDocument();
  expect(
    within(queue).queryByText('No items need your attention today.'),
  ).not.toBeInTheDocument();
});

test('renders canonical deduplicated actions without rebuilding downstream blockers', async () => {
  const state = accountFixture();
  state.overview.user_attention = [
    {
      schema_version: 'karkinos.operations_attention_item.v1',
      subsystem_id: 'market_data',
      status: 'blocked',
      target: 'market',
      evidence: { status: 'stale', observed_at: null },
      next_action: 'review_current_holding_market_evidence',
      resolution_condition: 'new_complete_market_evidence_required',
      task_fingerprint: 'one-root-cause',
      manual_acknowledgement_clears_status: false,
      read_only_projection: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
    },
  ];
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('1')).toBeVisible();
  expect(within(queue).getAllByRole('link')).toHaveLength(1);
  expect(within(queue).getByRole('link')).toHaveAttribute('href', '/market');
  expect(queue).not.toHaveTextContent('authorizes_execution');
});

test('a failed equity widget preserves the account canvas and holdings', async () => {
  installFetch(accountFixture(), true);
  renderPage();
  await screen.findByText(/Failed to load equity curve/);
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  expect(screen.getByTestId('overview-holdings-section')).toBeVisible();
});

test('a failed account refresh retains the prior coherent financial view', async () => {
  const mock = installFetch();
  const { client } = renderPage();
  await screen.findByTestId('overview-summary');
  mock.mockImplementation(
    async () => new Response('unavailable', { status: 503 }),
  );
  await act(async () => {
    await client.refetchQueries({ queryKey: ['account-state'] });
  });
  expect(screen.getByTestId('overview-total-value')).toHaveTextContent(
    '18,585.11',
  );
  await userEvent.click(screen.getByText('Data details'));
  expect(screen.getByText(/Could not refresh this view/)).toBeVisible();
});

test('range control requests only a supported canonical series range', async () => {
  const mock = installFetch();
  renderPage();
  await screen.findByTestId('equity-range-controls');
  await userEvent.click(screen.getByRole('button', { name: /6M/ }));
  await waitFor(() =>
    expect(mock).toHaveBeenCalledWith(
      '/api/portfolio/equity-curve/series?range=6m',
      expect.anything(),
    ),
  );
});

test('Chinese presentation preserves published NAV and compact no-action semantics', async () => {
  installFetch();
  renderPage('zh');
  expect(
    await screen.findByRole('heading', { name: '投资总览' }),
  ).toBeVisible();
  expect(await screen.findByText('今天没有需要处理的事项')).toBeVisible();
  expect(
    screen.getAllByTestId('position-pricing-fixture-fund')[0],
  ).toHaveTextContent('已公布净值 · 09/11');
});

test.each(['missing', 'conflicting', 'unknown'] as const)(
  'preserves %s price authority as explicit unverified evidence',
  async (authority) => {
    const state = accountFixture();
    state.snapshot.positions[0].pricing_authority = authority;
    state.overview.valuation_usability = 'unavailable';
    state.summary.total_equity = null;
    installFetch(state);
    renderPage();
    expect(await screen.findByTestId('overview-total-value')).toHaveTextContent(
      '--',
    );
    expect(
      screen.getAllByTestId('position-pricing-fixture-fund')[0],
    ).toHaveTextContent(
      authority === 'missing'
        ? 'Price evidence missing'
        : authority === 'conflicting'
          ? 'Conflicting price evidence'
          : 'Pricing unverified',
    );
    expect(screen.getByTestId('overview-data-status')).toHaveTextContent(
      'Valuation unavailable',
    );
  },
);

test('stock closing prices use the close basis in the primary as-of summary', async () => {
  const state = accountFixture();
  state.snapshot.positions[0] = {
    ...state.snapshot.positions[0],
    asset_class: 'stock',
    instrument_type: 'stock',
    pricing_kind: 'session_close',
  };
  installFetch(state);
  renderPage('zh');
  expect(await screen.findByTestId('overview-data-status')).toHaveTextContent(
    '数据截至 09/11 收盘 · 市场休市 · 当前估值可用',
  );
});

test('usable authoritative fund NAV stays published when live-decision quote freshness is blocked', async () => {
  const state = accountFixture();
  state.snapshot.positions[0].quote_status = 'stale';
  state.snapshot.positions[0].stale_reason =
    'quote_older_than_expected_session';
  state.snapshot.positions[0].valuation_available = true;
  state.overview.decision_readiness = 'blocked';
  installFetch(state);
  renderPage();
  await screen.findByTestId('overview-summary');
  const pricing = screen.getAllByTestId('position-pricing-fixture-fund')[0];
  expect(pricing).toHaveTextContent('Published NAV · 09/11');
  expect(pricing).not.toHaveTextContent(/update required|older than expected/);
  expect(screen.getByTestId('overview-data-status')).toHaveTextContent(
    'Current valuation usable',
  );
});

test('known valuation repair remains actionable when unrelated Operations evidence is unavailable', async () => {
  const state = accountFixture();
  state.overview.user_attention = [
    {
      schema_version: 'karkinos.operations_attention_item.v1',
      subsystem_id: 'market_data',
      status: 'blocked',
      target: 'market',
      evidence: { status: 'stale', observed_at: null },
      next_action: 'review_current_holding_market_evidence',
      resolution_condition: 'new_complete_market_evidence_required',
      task_fingerprint: 'one-root-cause',
      manual_acknowledgement_clears_status: false,
      read_only_projection: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
    },
  ];
  state.overview.attention_status = 'unavailable';
  installFetch(state);
  renderPage();
  const queue = await screen.findByTestId('overview-today-queue');
  expect(within(queue).getByText('--')).toBeVisible();
  expect(within(queue).getByText('Attention status unavailable')).toBeVisible();
  expect(within(queue).getAllByRole('link')).toHaveLength(2);
  expect(
    within(queue).getByRole('link', {
      name: 'Review current holding prices and NAV',
    }),
  ).toHaveAttribute('href', '/market');
  expect(queue).not.toHaveTextContent('authorizes_execution');
});

test('shows previous-session performance contributors from canonical account state', async () => {
  const state = accountFixture();
  state.summary.today_contributors = [
    {
      symbol: 'fixture-fund',
      display_name: '合成基金',
      asset_class: 'fund',
      today_change: -314.51,
    },
  ];
  installFetch(state);
  renderPage('zh');
  const drivers = await screen.findByTestId('overview-performance-drivers');
  expect(drivers).toHaveTextContent('上一交易日主要影响');
  expect(drivers).toHaveTextContent('合成基金');
  expect(drivers).toHaveTextContent('-¥314.51');
});
