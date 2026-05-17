import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { BacktestPage } from './backtest-page';

const savedSummary = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  strategy: 'dual_ma',
  total_return: 0.082,
  sharpe: 1.27,
  max_drawdown: 0.044,
};

const savedReport = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  config: {
    start_date: '2025-01-02',
    end_date: '2026-05-15',
    initial_cash: 100000,
    strategy: 'dual_ma',
    short_period: 5,
    long_period: 20,
    assets: [{ symbol: '600519', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 108200,
    total_return: 0.082,
    annual_return: 0.11,
    sharpe: 1.27,
    sortino: 1.56,
    max_drawdown: 0.044,
    calmar: 2.5,
    volatility: 0.14,
    win_rate: 0.58,
    duration_days: 260,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  metrics_json: {
    calmar: 2.5,
    volatility: 0.14,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  cost_summary_json: {
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  fills: [],
  equity_curve: [],
};

const runReport = {
  ...savedReport,
  id: 2,
  created_at: '',
  metrics: {
    ...savedReport.metrics,
    final_equity: 112000,
    total_return: 0.12,
    max_drawdown: 0.06,
  },
  metrics_json: {
    ...savedReport.metrics_json,
    calmar: 3.1,
    total_trades: 3,
  },
  cost_summary_json: {
    total_commission: 12.5,
    total_slippage: 3.5,
    total_trades: 3,
    gross_turnover: 24000,
  },
  fills: [],
  equity_curve: [],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installBacktestFetchMock({
  runFails = false,
  results = [savedSummary],
}: {
  runFails?: boolean;
  results?: unknown[];
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/backtest/run')) {
      return runFails
        ? jsonResponse({ detail: 'backtest unavailable' }, { status: 503 })
        : jsonResponse(runReport);
    }
    if (url.includes('/api/backtest/results/1')) {
      return jsonResponse(savedReport);
    }
    if (url.includes('/api/backtest/results')) {
      return jsonResponse(results);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderBacktestPage(
  options?: Parameters<typeof installBacktestFetchMock>[0],
) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installBacktestFetchMock(options);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <BacktestPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the backtest workspace and saved report history', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Strategy replay')).toBeTruthy();
  expect(await screen.findByText('Backtest configuration')).toBeTruthy();
  expect(await screen.findByText('Report selection')).toBeTruthy();
  expect(await screen.findByText('Equity and drawdown')).toBeTruthy();
});

test('runs a backtest and displays metrics_json and cost_summary_json fields', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  expect(await screen.findByText('Run output')).toBeTruthy();
  expect(await screen.findByText('Calmar 3.10')).toBeTruthy();
  expect(await screen.findByText('3 fills')).toBeTruthy();
  expect(
    await screen.findByText(
      'No equity curve is available for this backtest result.',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'No fill details are available for this saved result. New runs expose per-fill cost records when the backtest engine returns them.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('NaN')).toBeNull();
});

test('shows a clear error when the run endpoint fails', async () => {
  renderBacktestPage({ runFails: true, results: [] });

  await screen.findByText('Strategy replay');
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  expect((await screen.findByRole('alert')).textContent).toContain(
    'backtest unavailable',
  );
  expect(screen.queryByText(/real-time/i)).toBeNull();
});
