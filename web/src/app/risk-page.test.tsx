import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { RiskPage } from './router';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const accountState = {
  summary: {
    total_equity: 120000,
    available_cash: 24000,
    total_deposits: 100000,
    positions_count: 3,
    unrealized_pnl: 1800,
    realized_pnl: 200,
    cash_ratio: 0.2,
    valuation_timestamp: '2026-06-12T15:00:00+08:00',
    quote_status: 'live',
  },
  snapshot: {
    cash: 24000,
    total_equity: 120000,
    total_deposits: 100000,
    positions: [],
    allocation: [
      {
        symbol: '600519',
        name: '贵州茅台',
        weight: 0.34,
        value: 40800,
        asset_class: 'stock',
      },
    ],
    allocation_grouped: [],
  },
  risks: [],
  next_step: 'Review manual confirmations before any execution.',
};

const riskAlerts = [
  {
    kind: 'cash_buffer',
    level: 'medium',
    title: 'Cash buffer is close to the floor',
    detail: 'Cash ratio is 20%; review before adding new buy orders.',
  },
];

const riskWorkspace = {
  metrics: [
    {
      key: 'cash_ratio',
      label: 'Cash ratio',
      value: 0.2,
      display_value: '20.0%',
      level: 'medium',
      detail: 'Immediate liquidity buffer.',
    },
  ],
  drawdown: {
    current_drawdown: 0.01,
    max_drawdown: 0.08,
    latest_equity: 120000,
    peak_equity: 121200,
    peak_timestamp: '2026-06-11T15:00:00+08:00',
    trough_timestamp: '2026-06-12T15:00:00+08:00',
  },
  drawdown_series: [
    {
      timestamp: '2026-06-12T15:00:00+08:00',
      equity: 120000,
      peak_equity: 121200,
      drawdown: 0.01,
    },
  ],
  exposure_buckets: [],
  concentration: [],
};

const explainability = {
  equity_bridge: [],
  recent_drivers: [],
  positions: [],
  timeline: [],
};

function installRiskFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/portfolio/state')) {
      return jsonResponse(accountState);
    }
    if (url.includes('/api/portfolio/risk-summary')) {
      return jsonResponse(riskAlerts);
    }
    if (url.includes('/api/portfolio/risk-workspace')) {
      return jsonResponse(riskWorkspace);
    }
    if (url.includes('/api/portfolio/explainability')) {
      return jsonResponse(explainability);
    }
    if (url.includes('/api/trading/kill-switch')) {
      return jsonResponse({
        kill_switch_enabled: false,
        reason: '',
        updated_at: null,
      });
    }
    if (url.includes('/api/trading/orders')) {
      return jsonResponse([]);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderRiskPage() {
  window.localStorage.clear();
  installRiskFetchMock();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <RiskPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders risk boundaries and blocking register without execution controls', async () => {
  renderRiskPage();

  expect(await screen.findByText('Risk workspace')).toBeTruthy();
  expect(await screen.findByText('Risk boundary register')).toBeTruthy();
  expect(await screen.findByText('Blocking register')).toBeTruthy();

  const boundaryRegister = await screen.findByTestId('risk-boundary-register');
  expect(boundaryRegister.className).toContain('min-w-0');
  expect(
    within(boundaryRegister).getByLabelText(
      'Risk boundary item: Cash Buffer 20.0% Healthy reserve',
    ),
  ).toBeTruthy();
  expect(
    within(boundaryRegister).getByText('Manual confirmation required'),
  ).toBeTruthy();

  const blockRegister = await screen.findByTestId('risk-blocking-register');
  expect(blockRegister.className).toContain('min-w-0');
  expect(within(blockRegister).getByText('cash_buffer')).toBeTruthy();
  expect(
    within(blockRegister).getByText('Cash buffer is close to the floor'),
  ).toBeTruthy();
  expect(screen.queryByText(/automatic execution/i)).toBeNull();
});
